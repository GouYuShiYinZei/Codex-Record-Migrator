from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


RootKey = Literal["codex_home", "appdata_roaming", "appdata_local"]
EntryKind = Literal["file", "sqlite"]
RestoreMode = Literal["merge", "overwrite"]


@dataclass(frozen=True)
class RootSpec:
    key: RootKey
    path: Path
    label: str


@dataclass(frozen=True)
class BackupOptions:
    codex_home: Path
    output_path: Path
    include_logs: bool = True
    include_config: bool = False
    include_appdata: bool = False
    include_sensitive: bool = False


@dataclass(frozen=True)
class BackupEntry:
    root_key: RootKey
    source_path: Path
    relative_path: str
    archive_path: str
    kind: EntryKind
    source_size: int
    label: str = ""


@dataclass
class BackupPlan:
    entries: list[BackupEntry] = field(default_factory=list)
    roots: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.entries)

    @property
    def source_size(self) -> int:
        return sum(entry.source_size for entry in self.entries)


@dataclass(frozen=True)
class RestoreOptions:
    backup_path: Path
    target_codex_home: Path
    mode: RestoreMode = "merge"
    include_appdata: bool = False
    create_snapshot: bool = True


@dataclass
class OperationResult:
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ManifestEntry:
    root_key: RootKey
    relative_path: str
    archive_path: str
    kind: EntryKind
    source_size: int
    stored_size: int
    sha256: str
    mtime: float | None


@dataclass
class BackupManifest:
    version: int
    app_version: str
    created_at: str
    roots: dict[str, str]
    options: dict[str, Any]
    entries: list[ManifestEntry]
    warnings: list[str]
    host: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BackupManifest":
        entries = [ManifestEntry(**entry) for entry in data.get("entries", [])]
        return cls(
            version=int(data.get("version", 1)),
            app_version=str(data.get("app_version", "")),
            created_at=str(data.get("created_at", "")),
            roots=dict(data.get("roots", {})),
            options=dict(data.get("options", {})),
            entries=entries,
            warnings=list(data.get("warnings", [])),
            host=dict(data.get("host", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "app_version": self.app_version,
            "created_at": self.created_at,
            "roots": self.roots,
            "options": self.options,
            "entries": [entry.__dict__ for entry in self.entries],
            "warnings": self.warnings,
            "host": self.host,
        }
