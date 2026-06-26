from __future__ import annotations

import json
import sqlite3
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codex_migrator.core import create_backup, load_manifest, restore_backup, verify_backup
from codex_migrator.models import BackupOptions, RestoreOptions


def make_state_db(path: Path, thread_id: str, rollout_path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            create table threads (
                id text primary key,
                rollout_path text not null,
                created_at integer not null,
                updated_at integer not null,
                source text not null,
                model_provider text not null,
                cwd text not null,
                title text not null,
                sandbox_policy text not null,
                approval_mode text not null,
                tokens_used integer not null default 0,
                has_user_event integer not null default 0,
                archived integer not null default 0,
                archived_at integer,
                git_sha text,
                git_branch text,
                git_origin_url text,
                cli_version text not null default '',
                first_user_message text not null default '',
                preview text not null default '',
                recency_at integer not null default 0,
                recency_at_ms integer not null default 0
            )
            """
        )
        conn.execute(
            "insert into threads (id, rollout_path, created_at, updated_at, source, model_provider, cwd, title, sandbox_policy, approval_mode) values (?,?,?,?,?,?,?,?,?,?)",
            (thread_id, rollout_path, 1, 1, "desktop", "openai", "C:\\tmp", "hello", "workspace-write", "never"),
        )
        conn.commit()
    finally:
        conn.close()


def make_codex_dev_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("create table automations (id text primary key, title text not null)")
        conn.execute("insert into automations (id, title) values ('auto-a', 'backup')")
        conn.commit()
    finally:
        conn.close()


def make_newer_state_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            create table threads (
                id text primary key,
                rollout_path text not null,
                created_at integer not null,
                updated_at integer not null,
                source text not null,
                model_provider text not null,
                cwd text not null,
                title text not null,
                sandbox_policy text not null,
                approval_mode text not null,
                future_required text not null
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source" / ".codex"
        target = root / "target" / ".codex"
        backup = root / "backup.codexbackup"
        session = source / "sessions" / "2026" / "06" / "26" / "rollout-2026-06-26T00-00-00-thread-a.jsonl"
        session.parent.mkdir(parents=True)
        session.write_text('{"type":"session_meta","payload":{"id":"thread-a"}}\n', encoding="utf-8")
        (source / "session_index.jsonl").write_text(
            json.dumps({"id": "thread-a", "thread_name": "hello", "updated_at": "2026-06-26T00:00:00Z"}) + "\n",
            encoding="utf-8",
        )
        make_state_db(source / "state_5.sqlite", "thread-a", str(session))
        make_codex_dev_db(source / "sqlite" / "codex-dev.db")

        result = create_backup(BackupOptions(codex_home=source, output_path=backup, include_logs=True))
        assert result.ok, result.message
        manifest = load_manifest(backup)
        assert manifest.entries
        assert any(entry.relative_path == "sqlite/codex-dev.db" for entry in manifest.entries)
        assert verify_backup(backup, full=True).ok

        target.mkdir(parents=True)
        make_state_db(target / "state_5.sqlite", "thread-existing", str(target / "sessions" / "existing.jsonl"))
        restore = restore_backup(RestoreOptions(backup_path=backup, target_codex_home=target, mode="merge"))
        assert restore.ok, restore.message
        assert (target / "sessions" / "2026" / "06" / "26" / session.name).exists()
        conn = sqlite3.connect(target / "state_5.sqlite")
        try:
            rows = conn.execute("select id, rollout_path from threads order by id").fetchall()
        finally:
            conn.close()
        ids = {row[0] for row in rows}
        assert {"thread-a", "thread-existing"} <= ids
        imported_path = dict(rows)["thread-a"]
        assert str(target) in imported_path
        assert (target / "sqlite" / "codex-dev.db").exists()

        newer_target = root / "newer-target" / ".codex"
        newer_target.mkdir(parents=True)
        make_newer_state_db(newer_target / "state_5.sqlite")
        newer_restore = restore_backup(RestoreOptions(backup_path=backup, target_codex_home=newer_target, mode="merge"))
        assert newer_restore.ok, newer_restore.message
        assert any("future_required" in warning for warning in newer_restore.warnings)

    print("smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
