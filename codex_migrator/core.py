from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from . import __version__
from .models import (
    BackupManifest,
    BackupOptions,
    BackupPlan,
    ManifestEntry,
    OperationResult,
    RestoreOptions,
)
from .paths import build_backup_plan, default_appdata_local, default_appdata_roaming, format_bytes


ProgressCallback = Callable[[str, int, int], None]


MANIFEST_PATH = "manifest.json"
SNAPSHOT_DIR = "_codex_migrator_pre_restore"
SQLITE_MERGE_TABLES: dict[str, list[str]] = {
    "state": [
        "threads",
        "thread_dynamic_tools",
        "thread_spawn_edges",
        "agent_jobs",
        "agent_job_items",
        "external_agent_config_imports",
    ],
    "goals": ["thread_goals"],
    "memories": ["stage1_outputs", "jobs"],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_zip_info(archive_path: str, source_path: Path) -> zipfile.ZipInfo:
    stat = source_path.stat()
    local_time = time.localtime(stat.st_mtime)
    date_time = local_time[:6]
    info = zipfile.ZipInfo(archive_path, date_time=date_time)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    return info


def _write_file_to_zip(zf: zipfile.ZipFile, source_path: Path, archive_path: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    stored = 0
    info = _safe_zip_info(archive_path, source_path)
    with source_path.open("rb") as src, zf.open(info, "w") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            dst.write(chunk)
            stored += len(chunk)
    return stored, digest.hexdigest()


def _sqlite_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro"


def _backup_sqlite(source_path: Path, temp_dir: Path) -> Path:
    target = temp_dir / source_path.name
    source_conn = sqlite3.connect(_sqlite_uri(source_path), uri=True)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()
    return target


def _manifest_for_plan(options: BackupOptions, plan: BackupPlan, entries: list[ManifestEntry]) -> BackupManifest:
    return BackupManifest(
        version=1,
        app_version=__version__,
        created_at=_now_iso(),
        roots=plan.roots,
        options={
            "include_logs": options.include_logs,
            "include_config": options.include_config,
            "include_appdata": options.include_appdata,
            "include_sensitive": options.include_sensitive,
        },
        entries=entries,
        warnings=plan.warnings,
        host={
            "hostname": platform.node(),
            "system": platform.platform(),
            "user": os.environ.get("USERNAME") or os.environ.get("USER") or "",
        },
    )


def create_backup_plan(options: BackupOptions) -> BackupPlan:
    return build_backup_plan(options)


def create_backup(options: BackupOptions, progress: ProgressCallback | None = None) -> OperationResult:
    plan = create_backup_plan(options)
    if not plan.entries:
        return OperationResult(False, "没有找到可备份的 Codex 记录。", warnings=plan.warnings)

    output = options.output_path.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_suffix(output.suffix + ".tmp")
    manifest_entries: list[ManifestEntry] = []
    warnings = list(plan.warnings)

    if progress:
        progress("开始创建备份包", 0, plan.file_count)

    try:
        with tempfile.TemporaryDirectory(prefix="codex-migrator-") as temp_name:
            temp_dir = Path(temp_name)
            with zipfile.ZipFile(temp_output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for index, entry in enumerate(plan.entries, start=1):
                    source_for_zip = entry.source_path
                    sqlite_temp: Path | None = None
                    if progress:
                        progress(f"写入 {entry.relative_path}", index - 1, plan.file_count)

                    if entry.kind == "sqlite":
                        try:
                            sqlite_temp = _backup_sqlite(entry.source_path, temp_dir)
                            source_for_zip = sqlite_temp
                        except Exception as exc:  # pragma: no cover - fallback is environment dependent
                            warnings.append(f"SQLite 快照失败，改用文件复制: {entry.source_path} ({exc})")
                            source_for_zip = entry.source_path

                    try:
                        stored_size, sha = _write_file_to_zip(zf, source_for_zip, entry.archive_path)
                        mtime = entry.source_path.stat().st_mtime
                    except OSError as exc:
                        warnings.append(f"跳过无法读取的文件: {entry.source_path} ({exc})")
                        continue
                    finally:
                        if sqlite_temp and sqlite_temp.exists():
                            sqlite_temp.unlink(missing_ok=True)

                    manifest_entries.append(
                        ManifestEntry(
                            root_key=entry.root_key,
                            relative_path=entry.relative_path,
                            archive_path=entry.archive_path,
                            kind=entry.kind,
                            source_size=entry.source_size,
                            stored_size=stored_size,
                            sha256=sha,
                            mtime=mtime,
                        )
                    )

                manifest = _manifest_for_plan(options, plan, manifest_entries)
                zf.writestr(
                    MANIFEST_PATH,
                    json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
                    compress_type=zipfile.ZIP_DEFLATED,
                )

        if output.exists():
            output.unlink()
        temp_output.replace(output)
    except Exception as exc:
        temp_output.unlink(missing_ok=True)
        return OperationResult(False, f"备份失败: {exc}", warnings=warnings)

    if progress:
        progress("备份完成", plan.file_count, plan.file_count)

    size = output.stat().st_size if output.exists() else 0
    return OperationResult(
        True,
        f"备份完成: {output}",
        details={
            "output": str(output),
            "files": len(manifest_entries),
            "source_size": plan.source_size,
            "archive_size": size,
        },
        warnings=warnings,
    )


def load_manifest(backup_path: Path) -> BackupManifest:
    with zipfile.ZipFile(backup_path, "r") as zf:
        with zf.open(MANIFEST_PATH) as manifest_file:
            data = json.loads(manifest_file.read().decode("utf-8"))
    return BackupManifest.from_dict(data)


def verify_backup(backup_path: Path, full: bool = False, progress: ProgressCallback | None = None) -> OperationResult:
    try:
        manifest = load_manifest(backup_path)
        with zipfile.ZipFile(backup_path, "r") as zf:
            names = set(zf.namelist())
            missing = [entry.archive_path for entry in manifest.entries if entry.archive_path not in names]
            if missing:
                return OperationResult(False, f"备份包缺少 {len(missing)} 个文件。", details={"missing": missing[:20]})
            if full:
                total = len(manifest.entries)
                for index, entry in enumerate(manifest.entries, start=1):
                    if progress:
                        progress(f"校验 {entry.relative_path}", index - 1, total)
                    digest = hashlib.sha256()
                    with zf.open(entry.archive_path, "r") as src:
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            digest.update(chunk)
                    if digest.hexdigest() != entry.sha256:
                        return OperationResult(False, f"校验失败: {entry.relative_path}")
                if progress:
                    progress("校验完成", total, total)
        return OperationResult(
            True,
            "备份包可读取。",
            details={
                "files": len(manifest.entries),
                "created_at": manifest.created_at,
                "source_size": sum(entry.source_size for entry in manifest.entries),
            },
            warnings=manifest.warnings,
        )
    except Exception as exc:
        return OperationResult(False, f"无法读取备份包: {exc}")


def _safe_target(root: Path, relative_path: str) -> Path:
    if relative_path.startswith("/") or relative_path.startswith("\\"):
        raise ValueError(f"非法路径: {relative_path}")
    normalized = Path(relative_path)
    if any(part == ".." for part in normalized.parts):
        raise ValueError(f"非法路径: {relative_path}")
    target = (root / normalized).resolve()
    root_resolved = root.resolve()
    if root_resolved != target and root_resolved not in target.parents:
        raise ValueError(f"路径越界: {relative_path}")
    return target


def _root_map(options: RestoreOptions) -> dict[str, Path]:
    roots: dict[str, Path] = {"codex_home": options.target_codex_home.expanduser()}
    if options.include_appdata:
        roaming = default_appdata_roaming()
        local = default_appdata_local()
        if roaming:
            roots["appdata_roaming"] = roaming
        if local:
            roots["appdata_local"] = local
    return roots


def _snapshot_existing(paths: Iterable[Path], target_codex_home: Path) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    snapshot_root = target_codex_home / SNAPSHOT_DIR
    snapshot_root.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_root / f"pre-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    common_root = target_codex_home.parent.resolve()
    with zipfile.ZipFile(snapshot_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in existing:
            if path.is_dir():
                continue
            try:
                relative = path.resolve().relative_to(common_root).as_posix()
            except ValueError:
                relative = path.name
            try:
                zf.write(path, relative)
                for suffix in ("-wal", "-shm"):
                    sibling = Path(str(path) + suffix)
                    if sibling.exists():
                        zf.write(sibling, sibling.resolve().relative_to(common_root).as_posix())
            except OSError:
                continue
    return snapshot_path


def _extract_zip_entry(zf: zipfile.ZipFile, archive_path: str, target: Path, mtime: float | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_name(target.name + ".codex-migrator-tmp")
    with zf.open(archive_path, "r") as src, temp_target.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    if mtime:
        os.utime(temp_target, (mtime, mtime))
    temp_target.replace(target)


def _merge_jsonl(zf: zipfile.ZipFile, archive_path: str, target: Path) -> tuple[int, int]:
    target.parent.mkdir(parents=True, exist_ok=True)
    seen_ids: set[str] = set()
    needs_newline = False
    if target.exists():
        with target.open("r", encoding="utf-8", errors="replace") as existing:
            for line in existing:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                item_id = item.get("id")
                if isinstance(item_id, str):
                    seen_ids.add(item_id)
        if target.stat().st_size > 0:
            with target.open("rb") as existing_raw:
                existing_raw.seek(-1, os.SEEK_END)
                needs_newline = existing_raw.read(1) not in {b"\n", b"\r"}

    added = 0
    skipped = 0
    with zf.open(archive_path, "r") as src, target.open("a", encoding="utf-8", newline="\n") as dst:
        if needs_newline:
            dst.write("\n")
        for raw in src:
            text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError:
                dst.write(text + "\n")
                added += 1
                continue
            item_id = item.get("id")
            if isinstance(item_id, str) and item_id in seen_ids:
                skipped += 1
                continue
            if isinstance(item_id, str):
                seen_ids.add(item_id)
            dst.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
            added += 1
    return added, skipped


def _sqlite_family(path: Path) -> str | None:
    stem = path.name.split("_", 1)[0].lower()
    return stem if stem in SQLITE_MERGE_TABLES else None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("select 1 from sqlite_master where type='table' and name=?", (table,)).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f'pragma table_info("{table}")')]


def _insert_or_ignore_rows(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    table: str,
    source_codex_home: str,
    target_codex_home: str,
) -> int:
    source_cols = _table_columns(source_conn, table)
    target_cols = _table_columns(target_conn, table)
    columns = [col for col in source_cols if col in target_cols]
    if not columns:
        return 0

    target_info = list(target_conn.execute(f'pragma table_info("{table}")'))
    source_col_set = set(source_cols)
    missing_required = [
        row[1]
        for row in target_info
        if row[1] not in source_col_set and row[3] and row[4] is None and not row[5]
    ]
    if missing_required:
        raise ValueError(f"目标表 {table} 有源库缺失的必填字段: {', '.join(missing_required)}")

    placeholders = ",".join("?" for _ in columns)
    quoted_cols = ",".join(f'"{col}"' for col in columns)
    select_cols = ",".join(f'"{col}"' for col in columns)
    inserted = 0
    rows = source_conn.execute(f'select {select_cols} from "{table}"')
    for row in rows:
        values = list(row)
        if table == "threads" and "rollout_path" in columns:
            idx = columns.index("rollout_path")
            value = values[idx]
            if isinstance(value, str) and source_codex_home:
                normalized_source = source_codex_home.rstrip("\\/")
                if value.lower().startswith(normalized_source.lower()):
                    suffix = value[len(normalized_source) :].lstrip("\\/")
                    values[idx] = str(Path(target_codex_home) / Path(suffix))
        before = target_conn.total_changes
        target_conn.execute(
            f'insert or ignore into "{table}" ({quoted_cols}) values ({placeholders})',
            values,
        )
        if target_conn.total_changes > before:
            inserted += 1
    return inserted


def _merge_sqlite_database(
    source_db: Path,
    target_db: Path,
    source_codex_home: str,
    target_codex_home: str,
) -> tuple[dict[str, int], list[str]]:
    family = _sqlite_family(target_db)
    if not family:
        return {}, []

    inserted: dict[str, int] = {}
    warnings: list[str] = []
    source_conn = sqlite3.connect(source_db)
    target_conn = sqlite3.connect(target_db)
    try:
        target_conn.execute("pragma foreign_keys=off")
        for table in SQLITE_MERGE_TABLES[family]:
            if not _table_exists(source_conn, table) or not _table_exists(target_conn, table):
                continue
            try:
                count = _insert_or_ignore_rows(source_conn, target_conn, table, source_codex_home, target_codex_home)
                inserted[table] = count
            except (sqlite3.DatabaseError, ValueError) as exc:
                warnings.append(f"跳过 SQLite 表 {target_db.name}.{table}: {exc}")
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()
    return inserted, warnings


def restore_backup(options: RestoreOptions, progress: ProgressCallback | None = None) -> OperationResult:
    try:
        manifest = load_manifest(options.backup_path)
    except Exception as exc:
        return OperationResult(False, f"无法读取备份包: {exc}")

    root_map = _root_map(options)
    warnings = list(manifest.warnings)
    restored = 0
    skipped = 0
    merged = 0
    snapshot_path: Path | None = None

    target_paths: list[Path] = []
    for entry in manifest.entries:
        root = root_map.get(entry.root_key)
        if not root:
            continue
        try:
            target_paths.append(_safe_target(root, entry.relative_path))
        except ValueError as exc:
            warnings.append(str(exc))

    if options.create_snapshot:
        try:
            snapshot_path = _snapshot_existing(target_paths, options.target_codex_home.expanduser())
        except Exception as exc:
            warnings.append(f"恢复前快照失败，继续恢复: {exc}")

    total = len(manifest.entries)
    source_codex_home = manifest.roots.get("codex_home", "")
    target_codex_home = str(options.target_codex_home.expanduser())

    try:
        with tempfile.TemporaryDirectory(prefix="codex-restore-") as temp_name:
            temp_dir = Path(temp_name)
            with zipfile.ZipFile(options.backup_path, "r") as zf:
                for index, entry in enumerate(manifest.entries, start=1):
                    root = root_map.get(entry.root_key)
                    if not root:
                        skipped += 1
                        continue
                    if progress:
                        progress(f"恢复 {entry.relative_path}", index - 1, total)
                    target = _safe_target(root, entry.relative_path)

                    if options.mode == "merge" and entry.relative_path == "session_index.jsonl":
                        added, dupes = _merge_jsonl(zf, entry.archive_path, target)
                        merged += added
                        skipped += dupes
                        continue

                    if options.mode == "merge" and target.exists():
                        if entry.kind == "sqlite" and _sqlite_family(target):
                            temp_db = temp_dir / target.name
                            _extract_zip_entry(zf, entry.archive_path, temp_db)
                            changes, merge_warnings = _merge_sqlite_database(
                                temp_db,
                                target,
                                source_codex_home,
                                target_codex_home,
                            )
                            warnings.extend(merge_warnings)
                            merged += sum(changes.values())
                            if not changes:
                                skipped += 1
                            continue
                        skipped += 1
                        continue

                    _extract_zip_entry(zf, entry.archive_path, target, entry.mtime)
                    if entry.kind == "sqlite":
                        for suffix in ("-wal", "-shm"):
                            Path(str(target) + suffix).unlink(missing_ok=True)
                    restored += 1
    except Exception as exc:
        return OperationResult(
            False,
            f"恢复失败: {exc}",
            details={"snapshot": str(snapshot_path) if snapshot_path else ""},
            warnings=warnings,
        )

    if progress:
        progress("恢复完成", total, total)

    details = {
        "restored": restored,
        "merged": merged,
        "skipped": skipped,
        "snapshot": str(snapshot_path) if snapshot_path else "",
    }
    return OperationResult(True, "恢复完成。", details=details, warnings=warnings)


def summarize_plan(plan: BackupPlan) -> str:
    by_label: dict[str, tuple[int, int]] = {}
    for entry in plan.entries:
        files, size = by_label.get(entry.label, (0, 0))
        by_label[entry.label] = (files + 1, size + entry.source_size)
    lines = [
        f"文件数量: {plan.file_count}",
        f"源文件总大小: {format_bytes(plan.source_size)}",
        "",
    ]
    for label, (files, size) in sorted(by_label.items()):
        lines.append(f"{label}: {files} 个文件，{format_bytes(size)}")
    if plan.warnings:
        lines.append("")
        lines.append("警告:")
        lines.extend(f"- {warning}" for warning in plan.warnings)
    return "\n".join(lines)


def summarize_manifest(manifest: BackupManifest) -> str:
    by_root: dict[str, tuple[int, int]] = {}
    for entry in manifest.entries:
        files, size = by_root.get(entry.root_key, (0, 0))
        by_root[entry.root_key] = (files + 1, size + entry.source_size)
    lines = [
        f"创建时间: {manifest.created_at}",
        f"工具版本: {manifest.app_version}",
        f"文件数量: {len(manifest.entries)}",
        f"源文件总大小: {format_bytes(sum(entry.source_size for entry in manifest.entries))}",
        "",
    ]
    for root_key, (files, size) in sorted(by_root.items()):
        root_path = manifest.roots.get(root_key, "")
        lines.append(f"{root_key}: {files} 个文件，{format_bytes(size)}")
        if root_path:
            lines.append(f"  来源: {root_path}")
    if manifest.warnings:
        lines.append("")
        lines.append("备份时警告:")
        lines.extend(f"- {warning}" for warning in manifest.warnings)
    return "\n".join(lines)
