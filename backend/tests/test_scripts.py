"""Tests for shell scripts in scripts/, run as subprocesses.

F1.2 (D2): scripts/assert-schema-code-compat.sh's parsing must be testable
without a live linked project. The script exposes find_missing_versions()
and only runs main() when executed directly, so tests can source it and
call the function in isolation.
"""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "assert-schema-code-compat.sh"
ORDER_SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "check-migration-order.sh"


def _find_missing_versions(stdin_text: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f"source {SCRIPT} && find_missing_versions"],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestFindMissingVersions:
    def test_every_migration_present_in_both_columns_passes(self):
        stdin = (
            '{"migrations":['
            '{"local":"20260101000001","remote":"20260101000001","time":"t"},'
            '{"local":"20260102000001","remote":"20260102000001","time":"t"}'
            "]}"
        )
        result = _find_missing_versions(stdin)

        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_local_only_migration_is_reported_missing(self):
        """This is the exact shape that shipped broken: the old grep-based
        parser pulled the version out of the *local* column even though
        remote was empty, so the gate could never fail. Fails against the
        pre-F1.2 script (grep -oE '[0-9]{14}' over the whole raw output).
        """
        stdin = (
            '{"migrations":['
            '{"local":"20260101000001","remote":"20260101000001","time":"t"},'
            '{"local":"20260811000004","remote":"","time":"t"}'
            "]}"
        )
        result = _find_missing_versions(stdin)

        assert result.returncode == 0
        assert result.stdout.strip() == "20260811000004"

    def test_multiple_missing_versions_all_reported(self):
        stdin = (
            '{"migrations":['
            '{"local":"20260811000001","remote":"","time":"t"},'
            '{"local":"20260811000002","remote":"","time":"t"}'
            "]}"
        )
        result = _find_missing_versions(stdin)

        assert result.returncode == 0
        assert set(result.stdout.split()) == {"20260811000001", "20260811000002"}

    def test_malformed_output_fails_loudly_not_silently(self):
        """A gate that exits 0 when it cannot verify is not a gate."""
        result = _find_missing_versions("not json at all")

        assert result.returncode != 0
        assert result.stdout.strip() == ""

    def test_empty_output_fails_loudly_not_silently(self):
        result = _find_missing_versions("")

        assert result.returncode != 0
        assert result.stdout.strip() == ""

    def test_json_without_migrations_array_fails_loudly(self):
        result = _find_missing_versions('{"message":"unexpected shape"}')

        assert result.returncode != 0
        assert result.stdout.strip() == ""


class TestScriptRequiresLinkedFlag:
    def test_missing_linked_flag_exits_nonzero(self):
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 1
        assert "--linked is required" in result.stdout


class TestMainExitCodeWithFakeSupabaseCli:
    """End-to-end: stub the `supabase` binary on PATH so main() itself is
    exercised, not just the parsing function. This is the gate that guards
    the production cutover — it must actually fail when something is
    missing remotely.
    """

    def _run_with_fake_cli(
        self, tmp_path, fake_cli_body: str, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess:
        fake_supabase = tmp_path / "supabase"
        fake_supabase.write_text(f"#!/usr/bin/env bash\n{fake_cli_body}\n")
        fake_supabase.chmod(0o755)
        env = {"PATH": f"{tmp_path}:/usr/bin:/bin:/opt/homebrew/bin"}
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", str(SCRIPT), "--linked"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )

    def test_exits_1_when_a_migration_is_missing_remotely(self, tmp_path):
        result = self._run_with_fake_cli(
            tmp_path,
            'echo \'{"migrations":[{"local":"20260811000004","remote":"","time":"t"}]}\'',
        )

        assert result.returncode == 1
        assert "20260811000004" in result.stdout

    def test_exits_0_when_everything_is_applied_remotely(self, tmp_path):
        result = self._run_with_fake_cli(
            tmp_path,
            'echo \'{"migrations":[{"local":"20260811000004","remote":"20260811000004","time":"t"}]}\'',
        )

        assert result.returncode == 0

    def test_exits_1_when_cli_output_is_malformed(self, tmp_path):
        result = self._run_with_fake_cli(tmp_path, "echo 'not json'")

        assert result.returncode == 1

    def test_accepts_connection_progress_before_json(self, tmp_path):
        result = self._run_with_fake_cli(
            tmp_path,
            'echo "Connecting to remote database..."; '
            'echo \'{"migrations":[{"local":"20260811000004","remote":"20260811000004","time":"t"}]}\'',
        )

        assert result.returncode == 0

    def test_uses_database_password_for_remote_migration_query(self, tmp_path):
        args_file = tmp_path / "supabase-args"
        result = self._run_with_fake_cli(
            tmp_path,
            f'printf "%s\\n" "$@" > "{args_file}"; '
            'echo \'{"migrations":[{"local":"20260811000004","remote":"20260811000004","time":"t"}]}\'',
            {"SUPABASE_DB_PASSWORD": "staging-password"},
        )

        assert result.returncode == 0
        assert args_file.read_text().splitlines() == [
            "migration",
            "list",
            "--linked",
            "--output-format",
            "json",
            "--password",
            "staging-password",
        ]


class TestMigrationOrder:
    def _repo(self, tmp_path, new_name: str):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        migrations = repo / "supabase" / "migrations"
        migrations.mkdir(parents=True)
        (migrations / "20260811000004_existing.sql").write_text("-- base\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"],
            check=True,
        )
        (migrations / new_name).write_text("-- new\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "new"],
            check=True,
        )
        return repo

    def _run(self, repo):
        return subprocess.run(
            ["bash", str(ORDER_SCRIPT), "HEAD~1"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_rejects_lower_numbered_new_migration(self, tmp_path):
        result = self._run(self._repo(tmp_path, "20260811000001_out_of_order.sql"))

        assert result.returncode == 1
        assert "20260811000001" in result.stderr

    def test_accepts_newer_migration(self, tmp_path):
        result = self._run(self._repo(tmp_path, "20260811000005_ordered.sql"))

        assert result.returncode == 0
        assert "ordered" in result.stdout
