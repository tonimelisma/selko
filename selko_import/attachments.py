"""Copy attachment files from Supabase Storage into ``<data dir>/attachments/``.

The database import carries each ``attachments`` row with its ``storage_path``;
this copies the bytes those rows point at (04-data-cutover.md §B.7):

- The object list comes from ``storage.objects`` (bucket ``attachments``) in the
  source database, joined to ``public.attachments`` for ``content_hash``.
- Bytes come from the Storage API with a secret key read from a file.
- Every file is written to a temporary name, fsynced, then renamed, and checked
  against the object's size and, where the row has one, its SHA-256.
- Restartable: a file already present with the right size and hash is
  skipped, so the copy can run early and again for the delta at the freeze.
- Not copied: files of the removed Google Photos ingestion, which used the same
  bucket under ``{user_id}/photos/...``. An object there that no attachments row
  names is counted, not copied (an attachment's own path is always
  ``{user_id}/{uuid12}_{filename}``, so the two never collide).
- Output is counts only: no names, paths, ids or keys.

Exit codes: 0 every object copied and verified; 6 some objects were missing at
the source or did not match their size/hash (the rest are in place); 7 the
Storage API refused the key or the request.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

OBJECTS_SQL = (
    "SELECT o.name, (o.metadata->>'size')::bigint AS size, a.content_hash, a.id IS NOT NULL AS has_row"
    " FROM storage.objects o"
    " LEFT JOIN public.attachments a ON a.storage_path = o.name"
    " WHERE o.bucket_id = 'attachments'"
    " ORDER BY o.name"
)
CHUNK = 1 << 16


class CopyError(RuntimeError):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class CopyReport:
    objects: int = 0
    copied: int = 0
    skipped: int = 0
    missing: int = 0
    mismatched: int = 0
    bytes_copied: int = 0
    orphans: int = 0  # objects with no attachments row; copied all the same
    photo_objects: int = 0  # removed photo ingestion's files; not copied
    rows_without_file: int = 0  # attachments rows whose object the source lacks
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing or self.mismatched)


def _target(root: Path, name: str) -> Path:
    """The local path for an object name; refuses anything outside ``root``."""
    if not name or name.startswith("/") or "\\" in name or any(part in ("", ".", "..") for part in name.split("/")):
        raise CopyError("an object name is not a plain relative path", 6)
    path = (root / name).resolve()
    if root.resolve() not in path.parents:
        raise CopyError("an object name points outside the attachments directory", 6)
    return path


def _matches(path: Path, size: int | None, content_hash: str | None) -> bool:
    if not path.is_file():
        return False
    if size is not None and path.stat().st_size != size:
        return False
    if content_hash:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(CHUNK), b""):
                digest.update(block)
        return digest.hexdigest() == content_hash.lower()
    return True


def is_photo_object(name: str, has_row: bool) -> bool:
    """A file of the removed photo ingestion: ``{user_id}/photos/...`` with no attachments row."""
    parts = name.split("/")
    return not has_row and len(parts) >= 3 and parts[1] == "photos"


async def _objects(source_url: str) -> tuple[list[tuple[str, int | None, str | None, bool]], int]:
    import asyncpg  # only the importer needs a Postgres driver

    conn = await asyncpg.connect(source_url, statement_cache_size=0)
    try:
        rows = await conn.fetch(OBJECTS_SQL)
        without = await conn.fetchval(
            "SELECT count(*) FROM public.attachments a WHERE a.storage_path IS NOT NULL AND NOT EXISTS"
            " (SELECT 1 FROM storage.objects o WHERE o.bucket_id = 'attachments' AND o.name = a.storage_path)"
        )
    finally:
        await conn.close()
    return [(r["name"], r["size"], r["content_hash"], r["has_row"]) for r in rows], int(without or 0)


def _download(client, base_url: str, key: str, name: str, temp: Path) -> int | None:
    """Stream one object into ``temp``. Returns its byte count, or None when missing."""
    import httpx

    url = f"{base_url.rstrip('/')}/storage/v1/object/authenticated/attachments/{quote(name)}"
    headers = {"Authorization": f"Bearer {key}", "apikey": key}
    for attempt in range(4):
        try:
            with client.stream("GET", url, headers=headers) as response:
                if response.status_code == 404 or (response.status_code == 400 and _is_not_found(response)):
                    return None
                if response.status_code in (429,) or response.status_code >= 500:
                    raise httpx.TransportError(f"retryable status {response.status_code}")
                if response.status_code >= 400:
                    raise CopyError(f"the Storage API refused the request with {response.status_code}", 7)
                written = 0
                with temp.open("wb") as handle:
                    for block in response.iter_bytes(CHUNK):
                        handle.write(block)
                        written += len(block)
                    handle.flush()
                    os.fsync(handle.fileno())
                return written
        except httpx.TransportError:
            if attempt == 3:
                raise CopyError("the Storage API kept failing after retries", 7) from None
            import time

            time.sleep(2**attempt)
    return None  # pragma: no cover


def _is_not_found(response) -> bool:
    """Supabase Storage answers a missing object with 400 and a not_found body."""
    try:
        response.read()
        return "not_found" in response.text.lower() or "not found" in response.text.lower()
    except Exception:
        return False


def copy_attachments(
    source_url: str,
    storage_url: str,
    storage_key: str,
    attachments_dir: Path,
    progress: Callable[[str], None] = print,
) -> CopyReport:
    import asyncio

    import httpx

    objects, rows_without_file = asyncio.run(_objects(source_url))
    report = CopyReport(objects=len(objects), rows_without_file=rows_without_file)
    attachments_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=httpx.Timeout(10.0, read=60.0), follow_redirects=False) as client:
        for index, (name, size, content_hash, has_row) in enumerate(objects, 1):
            if is_photo_object(name, has_row):
                report.photo_objects += 1
                continue
            if not has_row:
                report.orphans += 1
            target = _target(attachments_dir, name)
            if _matches(target, size, content_hash):
                report.skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".copying")
            try:
                written = _download(client, storage_url, storage_key, name, temp)
                if written is None:
                    report.missing += 1
                    continue
                if not _matches(temp, size, content_hash):
                    report.mismatched += 1
                    continue
                os.chmod(temp, 0o600)
                os.replace(temp, target)
                report.copied += 1
                report.bytes_copied += written
            finally:
                temp.unlink(missing_ok=True)
            if index % 500 == 0:
                progress(f"attachments: {index}/{len(objects)} objects")
    progress(
        f"attachments: {report.objects} objects, {report.copied} copied ({report.bytes_copied} bytes),"
        f" {report.skipped} already in place, {report.missing} missing at source, {report.mismatched} not matching,"
        f" {report.orphans} without a row, {report.rows_without_file} rows whose object the source lacks,"
        f" {report.photo_objects} photo files not copied"
    )
    return report
