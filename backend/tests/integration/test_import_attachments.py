"""selko_import attachments: Supabase Storage objects -> <data dir>/attachments.

The source is the throwaway Postgres of test_import_from_postgres.py with a
`storage.objects` table added; Storage itself is a local HTTP server that
answers like Supabase's (Bearer key, 400 not_found for a missing object).
"""

from __future__ import annotations

import hashlib
import http.server
import json
import threading
from urllib.parse import unquote

import pytest

from tests.integration.test_import_from_postgres import (  # noqa: F401  (fixtures)
    fixture_source,
    importer,
    postgres_admin_url,
)

pytestmark = pytest.mark.integration

KEY = "test-storage-key"
USER = "11111111-1111-4111-8111-111111111111"
ATTACHMENT = "55555555-5555-4555-8555-555555555555"
TICKET = f"{USER}/{ATTACHMENT}/ticket.pdf"
ORPHAN = f"{USER}/orphan/notes.txt"
TICKET_BYTES = b"%PDF-1.4\n% fixture ticket\n" + bytes(range(256)) * 40
ORPHAN_BYTES = b"an object with no attachments row\n"


@pytest.fixture
def storage():
    """A Storage stand-in: {name: bytes}; set ``refuse`` to answer 403."""
    objects: dict[str, bytes] = {TICKET: TICKET_BYTES, ORPHAN: ORPHAN_BYTES}
    state = {"refuse": False, "requests": 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            state["requests"] += 1
            prefix = "/storage/v1/object/authenticated/attachments/"
            if state["refuse"] or self.headers.get("Authorization") != f"Bearer {KEY}" or self.headers.get("apikey") != KEY:
                self.send_response(403)
                self.end_headers()
                return
            name = unquote(self.path[len(prefix):]) if self.path.startswith(prefix) else None
            if name not in objects:
                body = json.dumps({"statusCode": "404", "error": "not_found", "message": "Object not found"}).encode()
                self.send_response(400)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            data = objects[name]
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"url": f"http://127.0.0.1:{server.server_address[1]}", "objects": objects, "state": state}
    finally:
        server.shutdown()


def _sql(url, statement):
    import asyncio

    import asyncpg

    async def go():
        conn = await asyncpg.connect(url)
        await conn.execute(statement)
        await conn.close()

    asyncio.run(go())


@pytest.fixture
def source(fixture_source):
    """The fixture database plus Storage's object table and real hashes/sizes."""
    _sql(fixture_source, f"""
        CREATE SCHEMA storage;
        CREATE TABLE storage.objects (bucket_id text, name text, metadata jsonb);
        INSERT INTO storage.objects VALUES
          ('attachments', '{TICKET}', '{{"size": {len(TICKET_BYTES)}}}'),
          ('attachments', '{ORPHAN}', '{{"size": {len(ORPHAN_BYTES)}}}'),
          ('other-bucket', 'not/ours.bin', '{{"size": 3}}');
        UPDATE public.attachments SET storage_path = '{TICKET}', size_bytes = {len(TICKET_BYTES)},
          content_hash = '{hashlib.sha256(TICKET_BYTES).hexdigest()}';
    """)
    return fixture_source


def _copy(source, storage, data_dir):
    from selko_import.attachments import copy_attachments

    return copy_attachments(source, storage["url"], KEY, data_dir / "attachments", progress=lambda _: None)


def test_copies_every_object_and_verifies_it(importer, source, storage, tmp_path):
    report = _copy(source, storage, tmp_path)
    assert report.ok and (report.objects, report.copied, report.orphans) == (2, 2, 1)
    ticket = tmp_path / "attachments" / TICKET
    assert ticket.read_bytes() == TICKET_BYTES
    assert oct(ticket.stat().st_mode & 0o777) == "0o600"
    assert (tmp_path / "attachments" / ORPHAN).read_bytes() == ORPHAN_BYTES
    assert not list((tmp_path / "attachments").rglob("*.copying"))


def test_a_second_run_copies_nothing_and_a_changed_file_is_recopied(importer, source, storage, tmp_path):
    _copy(source, storage, tmp_path)
    requests = storage["state"]["requests"]
    again = _copy(source, storage, tmp_path)
    assert (again.copied, again.skipped) == (0, 2)
    assert storage["state"]["requests"] == requests  # nothing fetched
    (tmp_path / "attachments" / TICKET).write_bytes(b"tampered")
    third = _copy(source, storage, tmp_path)
    assert (third.copied, third.skipped) == (1, 1)
    assert (tmp_path / "attachments" / TICKET).read_bytes() == TICKET_BYTES


def test_a_missing_or_corrupt_object_is_counted_and_not_kept(importer, source, storage, tmp_path):
    storage["objects"][TICKET] = TICKET_BYTES[:-1] + b"!"  # same size, wrong hash
    del storage["objects"][ORPHAN]
    report = _copy(source, storage, tmp_path)
    assert not report.ok and (report.mismatched, report.missing, report.copied) == (1, 1, 0)
    assert not (tmp_path / "attachments" / TICKET).exists()
    assert not list((tmp_path / "attachments").rglob("*.copying"))


def test_a_refused_key_stops_the_copy(importer, source, storage, tmp_path):
    from selko_import.attachments import CopyError

    storage["state"]["refuse"] = True
    with pytest.raises(CopyError) as exc:
        _copy(source, storage, tmp_path)
    assert exc.value.exit_code == 7


def test_an_object_name_outside_the_directory_is_refused(importer, source, storage, tmp_path):
    from selko_import.attachments import CopyError

    _sql(source, "INSERT INTO storage.objects VALUES ('attachments', '../escape.txt', '{\"size\": 1}')")
    with pytest.raises(CopyError):
        _copy(source, storage, tmp_path)
    assert not (tmp_path / "escape.txt").exists()


def test_files_of_the_removed_photo_ingestion_are_counted_not_copied(importer, source, storage, tmp_path):
    photo = f"{USER}/photos/abc123_beach.jpg"
    storage["objects"][photo] = b"jpeg bytes"
    _sql(source, f"INSERT INTO storage.objects VALUES ('attachments', '{photo}', '{{\"size\": 10}}')")
    before = storage["state"]["requests"]
    report = _copy(source, storage, tmp_path)
    assert report.ok and (report.objects, report.copied, report.photo_objects, report.orphans) == (3, 2, 1, 1)
    assert storage["state"]["requests"] - before == 2  # the photo was never downloaded
    assert not (tmp_path / "attachments" / photo).exists()


def test_an_attachment_row_is_copied_whatever_its_path_says(importer):
    from selko_import.attachments import is_photo_object

    assert is_photo_object("u/photos/x.jpg", has_row=False)
    assert not is_photo_object("u/photos/x.jpg", has_row=True)  # a row names it: an attachment
    assert not is_photo_object("u/abc_photos.jpg", has_row=False)
    assert not is_photo_object("photos/x.jpg", has_row=False)


def test_the_command_line_reads_secrets_from_files_and_reports_counts_only(importer, source, storage, tmp_path, capsys):
    from selko_import.__main__ import main

    url_file, key_file = tmp_path / "source.url", tmp_path / "storage.key"
    url_file.write_text(source)
    key_file.write_text(KEY)
    code = main(["attachments", "--source-url-file", str(url_file), "--storage-url", storage["url"],
                 "--storage-key-file", str(key_file), "--data-dir", str(tmp_path / "data")])
    out = capsys.readouterr()
    assert code == 0
    for secret in (KEY, source, TICKET, USER):
        assert secret not in out.out + out.err
