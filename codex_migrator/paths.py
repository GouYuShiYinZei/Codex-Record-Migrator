from __future__ import annotations

import os
import re
from pathlib import Path

from .models import BackupEntry, BackupOptions, BackupPlan, RootKey, RootSpec


SENSITIVE_FILE_NAMES = {
    "auth.json",
    "auth.json.bak",
    "cap_sid",
    "installation_id",
    "chrome-native-hosts-v2.json",
}

SENSITIVE_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
}

CORE_DIRS = {
    "sessions",
    "archived_sessions",
    "attachments",
    "generated_images",
}

CORE_STATE_DIRS = {
    "sqlite",
}

CORE_FILES = {
    ".codex-global-state.json",
    ".codex-global-state.json.bak",
    "session_index.jsonl",
    "history.jsonl",
    "external_agent_session_imports.json",
}

CONFIG_DIRS = {
    "hooks",
    "skills",
    "plugins",
    "memories",
    "ambient-suggestions",
}

CONFIG_FILES = {
    "AGENTS.md",
    "config.toml",
    "config.toml.bak",
    "hooks.json",
    "models_cache.json",
}

NOISY_DIRS = {
    ".sandbox",
    ".sandbox-bin",
    ".sandbox-secrets",
    ".tmp",
    "tmp",
    "cache",
    "log",
    "node_repl",
    "process_manager",
    "computer-use",
    "computer-use-turn-ended",
    "vendor_imports",
    "browser",
}

APPDATA_SKIP_DIRS = {
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnCache",
    "Crashpad",
    "BrowserMetrics",
    "GrShaderCache",
    "ShaderCache",
    "component_crx_cache",
}
APPDATA_SKIP_DIR_NAMES = {item.lower() for item in APPDATA_SKIP_DIRS}

SQLITE_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
}


def default_codex_home() -> Path:
    env_home = os.environ.get("CODEX_HOME")
    if env_home:
        return Path(env_home).expanduser()
    return Path.home() / ".codex"


def default_backup_dir() -> Path:
    candidates = [
        Path.home() / "Documents" / "CodexBackups",
        Path.home() / "CodexBackups",
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return Path.cwd()


def default_backup_name() -> str:
    from datetime import datetime

    return f"codex-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.codexbackup"


def default_appdata_roaming() -> Path | None:
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "Codex" if appdata else None


def default_appdata_local() -> Path | None:
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) / "Codex" if local else None


def is_sensitive_path(path: Path) -> bool:
    name = path.name.lower()
    if name in SENSITIVE_FILE_NAMES:
        return True
    if path.suffix.lower() in SENSITIVE_SUFFIXES:
        return True
    return any(part.lower() in {"cookies", "local storage", "session storage"} for part in path.parts)


def is_sqlite_file(path: Path) -> bool:
    if re.match(r"^(state|logs|goals|memories)_\d+\.sqlite$", path.name, re.IGNORECASE):
        return True
    return path.suffix.lower() in SQLITE_SUFFIXES


def is_log_sqlite(path: Path) -> bool:
    return bool(re.match(r"^logs_\d+\.sqlite$", path.name, re.IGNORECASE))


def format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _archive_path(root_key: RootKey, relative_path: str) -> str:
    return f"payload/{root_key}/{relative_path}"


def _should_skip_dir(path: Path, root: Path, include_sensitive: bool, appdata: bool = False) -> bool:
    name = path.name
    if appdata and name.lower() in APPDATA_SKIP_DIR_NAMES:
        return True
    if not appdata and _relative_path(path, root).split("/", 1)[0] in NOISY_DIRS:
        return True
    if not include_sensitive and is_sensitive_path(path):
        return True
    return False


def _iter_files(root: Path, include_sensitive: bool, appdata: bool = False):
    if not root.exists():
        return
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if not _should_skip_dir(child, root, include_sensitive, appdata=appdata):
                    stack.append(child)
                continue
            if child.is_file():
                if include_sensitive or not is_sensitive_path(child):
                    yield child


def _add_file(
    plan: BackupPlan,
    root_key: RootKey,
    root: Path,
    path: Path,
    label: str,
    seen: set[str],
) -> None:
    try:
        resolved = str(path.resolve()).lower()
        if resolved in seen:
            return
        seen.add(resolved)
        relative = _relative_path(path, root)
        stat = path.stat()
    except OSError as exc:
        plan.warnings.append(f"无法读取 {path}: {exc}")
        return
    kind = "sqlite" if is_sqlite_file(path) else "file"
    plan.entries.append(
        BackupEntry(
            root_key=root_key,
            source_path=path,
            relative_path=relative,
            archive_path=_archive_path(root_key, relative),
            kind=kind,
            source_size=stat.st_size,
            label=label,
        )
    )


def _add_directory(
    plan: BackupPlan,
    root_key: RootKey,
    root: Path,
    directory: Path,
    label: str,
    include_sensitive: bool,
    seen: set[str],
    appdata: bool = False,
) -> None:
    if not directory.exists():
        return
    for file_path in _iter_files(directory, include_sensitive=include_sensitive, appdata=appdata):
        _add_file(plan, root_key, root, file_path, label, seen)


def discover_roots(codex_home: Path) -> list[RootSpec]:
    roots = [RootSpec("codex_home", codex_home.expanduser(), "Codex 用户目录")]
    roaming = default_appdata_roaming()
    local = default_appdata_local()
    if roaming:
        roots.append(RootSpec("appdata_roaming", roaming, "Codex 桌面端 Roaming 数据"))
    if local:
        roots.append(RootSpec("appdata_local", local, "Codex 桌面端 Local 数据"))
    return roots


def build_backup_plan(options: BackupOptions) -> BackupPlan:
    codex_home = options.codex_home.expanduser()
    plan = BackupPlan(roots={"codex_home": str(codex_home)})
    seen: set[str] = set()

    if not codex_home.exists():
        plan.warnings.append(f"Codex 用户目录不存在: {codex_home}")
        return plan

    for dir_name in sorted(CORE_DIRS):
        _add_directory(
            plan,
            "codex_home",
            codex_home,
            codex_home / dir_name,
            "对话与附件",
            options.include_sensitive,
            seen,
        )

    for dir_name in sorted(CORE_STATE_DIRS):
        _add_directory(
            plan,
            "codex_home",
            codex_home,
            codex_home / dir_name,
            "SQLite 状态库",
            options.include_sensitive,
            seen,
        )

    for file_name in sorted(CORE_FILES):
        file_path = codex_home / file_name
        if file_path.exists():
            _add_file(plan, "codex_home", codex_home, file_path, "索引与全局状态", seen)

    for sqlite_path in sorted(codex_home.glob("*.sqlite")):
        if not options.include_logs and is_log_sqlite(sqlite_path):
            continue
        _add_file(plan, "codex_home", codex_home, sqlite_path, "SQLite 状态库", seen)

    if options.include_config:
        for dir_name in sorted(CONFIG_DIRS):
            _add_directory(
                plan,
                "codex_home",
                codex_home,
                codex_home / dir_name,
                "配置与扩展",
                options.include_sensitive,
                seen,
            )
        for file_name in sorted(CONFIG_FILES):
            file_path = codex_home / file_name
            if file_path.exists():
                _add_file(plan, "codex_home", codex_home, file_path, "配置与扩展", seen)

    if options.include_sensitive:
        for sensitive_name in sorted(SENSITIVE_FILE_NAMES):
            file_path = codex_home / sensitive_name
            if file_path.exists():
                _add_file(plan, "codex_home", codex_home, file_path, "敏感登录/设备文件", seen)
        plan.warnings.append("已启用敏感文件备份，请只把备份包保存到可信位置。")

    if options.include_appdata:
        roaming = default_appdata_roaming()
        local = default_appdata_local()
        if roaming and roaming.exists():
            plan.roots["appdata_roaming"] = str(roaming)
            _add_directory(
                plan,
                "appdata_roaming",
                roaming,
                roaming,
                "桌面端应用状态",
                options.include_sensitive,
                seen,
                appdata=True,
            )
        if local and local.exists():
            plan.roots["appdata_local"] = str(local)
            _add_directory(
                plan,
                "appdata_local",
                local,
                local,
                "桌面端应用状态",
                options.include_sensitive,
                seen,
                appdata=True,
            )
        if not options.include_sensitive:
            plan.warnings.append("桌面端 AppData 已排除 cookies、Local Storage 等可能包含登录态的目录。")

    return plan
