# Codex 记录备份迁移工具

这是一个 Windows 桌面工具，用来可视化备份、预览、校验和恢复 Codex 本地对话记录。适用场景包括账号失效风险、切换账号、换成 API 登录、迁移到新机器，或者在升级/重装前保留历史对话。

## 功能

- 扫描默认 Codex 用户目录：`%USERPROFILE%\.codex`
- 备份对话 JSONL、归档对话、附件、生成图片、索引文件和 SQLite 状态库
- 默认排除 `auth.json`、`cap_sid`、cookies、Local Storage 等敏感登录数据
- 备份包为 ZIP 结构，扩展名 `.codexbackup`，内含 `manifest.json`
- 支持恢复前自动快照
- 支持合并恢复和覆盖恢复
- 支持命令行模式，便于自动化
- 提供 Nuitka standalone 和 Inno Setup 安装包脚本

## 运行源码

```powershell
python .\main.py
```

命令行扫描：

```powershell
python .\main.py scan --codex-home "$env:USERPROFILE\.codex"
```

命令行备份：

```powershell
python .\main.py backup --output "$env:USERPROFILE\Documents\CodexBackups\codex.codexbackup"
```

命令行恢复：

```powershell
python .\main.py restore ".\codex.codexbackup" --target "$env:USERPROFILE\.codex" --mode merge
```

## 备份策略

默认包含：

- `sessions`
- `archived_sessions`
- `attachments`
- `generated_images`
- `session_index.jsonl`
- `history.jsonl`
- `external_agent_session_imports.json`
- `.codex-global-state.json`
- `state_*.sqlite`
- `goals_*.sqlite`
- `memories_*.sqlite`
- `logs_*.sqlite`
- `sqlite/*.db`

可选包含：

- `config.toml`
- `AGENTS.md`
- `hooks`
- `skills`
- `plugins`
- Codex 桌面端 AppData
- 敏感登录/设备文件

## 恢复策略

推荐默认使用“合并，不覆盖已有文件”：

- 对话 JSONL、附件、图片：目标不存在才写入
- `session_index.jsonl`：按 `id` 合并，备份包中的同 id 条目会修正目标端旧索引
- `sessions` / `archived_sessions`：合并模式下会自动修复同名但为空或被截断的对话文件
- `state_*.sqlite`、`goals_*.sqlite`、`memories_*.sqlite`：如果目标库已存在，会按主键插入或更新备份中已有字段，同时保留目标端新字段
- 遇到目标端新版本 SQLite 表结构不兼容时，会跳过该表并记录警告，避免中断整个恢复
- `logs_*.sqlite`：合并模式下已有目标库时跳过

“覆盖恢复”适合新账号、新机器或空白 Codex 环境。恢复前请关闭 Codex 桌面端和 CLI，避免 SQLite 被占用。

## Nuitka 打包

首次打包建议安装构建依赖：

```powershell
.\build.ps1 -InstallDeps
```

之后直接构建：

```powershell
.\build.ps1
```

输出：

```text
build\main.dist\CodexRecordMigrator.exe
```

## Inno Setup 安装包

安装 Inno Setup 6 后运行：

```powershell
.\installer\build-installer.ps1
```

输出目录：

```text
dist\
```

## 测试

```powershell
python -m compileall .\codex_migrator
python .\tests\smoke_test.py
```

## 注意

Codex 的本地数据结构可能随版本变化。这个工具采用“文件级备份 + manifest + 保守 SQLite 合并”的方式，优先保证原始数据可恢复。跨版本恢复前建议先用当前账号做一次备份，再执行迁移。
