from __future__ import annotations

import argparse
from pathlib import Path

from .core import (
    create_backup,
    create_backup_plan,
    restore_backup,
    summarize_manifest,
    summarize_plan,
    verify_backup,
    load_manifest,
)
from .models import BackupOptions, RestoreOptions
from .paths import default_backup_dir, default_backup_name, default_codex_home, format_bytes


def _progress(message: str, done: int, total: int) -> None:
    if total:
        print(f"[{done}/{total}] {message}")
    else:
        print(message)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-migrator", description="备份和迁移 Codex 本地对话记录。")
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="扫描可备份内容")
    scan.add_argument("--codex-home", type=Path, default=default_codex_home())
    scan.add_argument("--no-logs", action="store_true")
    scan.add_argument("--include-config", action="store_true")
    scan.add_argument("--include-appdata", action="store_true")
    scan.add_argument("--include-sensitive", action="store_true")

    backup = sub.add_parser("backup", help="创建备份包")
    backup.add_argument("--codex-home", type=Path, default=default_codex_home())
    backup.add_argument("--output", type=Path, default=default_backup_dir() / default_backup_name())
    backup.add_argument("--no-logs", action="store_true")
    backup.add_argument("--include-config", action="store_true")
    backup.add_argument("--include-appdata", action="store_true")
    backup.add_argument("--include-sensitive", action="store_true")

    inspect = sub.add_parser("inspect", help="读取备份包摘要")
    inspect.add_argument("backup", type=Path)

    verify = sub.add_parser("verify", help="校验备份包")
    verify.add_argument("backup", type=Path)
    verify.add_argument("--full", action="store_true", help="逐文件校验 SHA-256")

    restore = sub.add_parser("restore", help="恢复备份包")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--target", type=Path, default=default_codex_home())
    restore.add_argument("--mode", choices=["merge", "overwrite"], default="merge")
    restore.add_argument("--include-appdata", action="store_true")
    restore.add_argument("--no-snapshot", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    if args.command == "scan":
        options = BackupOptions(
            codex_home=args.codex_home,
            output_path=Path("unused.codexbackup"),
            include_logs=not args.no_logs,
            include_config=args.include_config,
            include_appdata=args.include_appdata,
            include_sensitive=args.include_sensitive,
        )
        print(summarize_plan(create_backup_plan(options)))
        return 0

    if args.command == "backup":
        options = BackupOptions(
            codex_home=args.codex_home,
            output_path=args.output,
            include_logs=not args.no_logs,
            include_config=args.include_config,
            include_appdata=args.include_appdata,
            include_sensitive=args.include_sensitive,
        )
        result = create_backup(options, _progress)
        print(result.message)
        if result.details:
            print(f"文件: {result.details.get('files', 0)}")
            print(f"备份包大小: {format_bytes(int(result.details.get('archive_size', 0)))}")
        for warning in result.warnings:
            print(f"警告: {warning}")
        return 0 if result.ok else 1

    if args.command == "inspect":
        print(summarize_manifest(load_manifest(args.backup)))
        return 0

    if args.command == "verify":
        result = verify_backup(args.backup, full=args.full, progress=_progress if args.full else None)
        print(result.message)
        for warning in result.warnings:
            print(f"警告: {warning}")
        return 0 if result.ok else 1

    if args.command == "restore":
        result = restore_backup(
            RestoreOptions(
                backup_path=args.backup,
                target_codex_home=args.target,
                mode=args.mode,
                include_appdata=args.include_appdata,
                create_snapshot=not args.no_snapshot,
            ),
            _progress,
        )
        print(result.message)
        if result.details:
            print(result.details)
        for warning in result.warnings:
            print(f"警告: {warning}")
        return 0 if result.ok else 1

    parser.print_help()
    return 2
