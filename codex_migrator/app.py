from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .core import (
    create_backup,
    create_backup_plan,
    load_manifest,
    restore_backup,
    summarize_manifest,
    summarize_plan,
    verify_backup,
)
from .models import BackupOptions, RestoreOptions
from .paths import default_backup_dir, default_backup_name, default_codex_home, format_bytes


class CodexMigratorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Codex 记录备份迁移工具")
        self.geometry("960x680")
        self.minsize(880, 600)

        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.active_thread: threading.Thread | None = None
        self._configure_style()
        self._build_ui()
        self.after(120, self._poll_queue)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", padding=(12, 6))
        style.configure("Accent.TButton", padding=(14, 7))
        style.configure("Header.TLabel", font=("Microsoft YaHei UI", 13, "bold"))
        style.configure("Muted.TLabel", foreground="#59636e")
        style.configure("Danger.TCheckbutton", foreground="#9c2f24")

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)

        self.backup_tab = ttk.Frame(notebook, padding=12)
        self.restore_tab = ttk.Frame(notebook, padding=12)
        self.about_tab = ttk.Frame(notebook, padding=12)
        notebook.add(self.backup_tab, text="备份")
        notebook.add(self.restore_tab, text="恢复/迁移")
        notebook.add(self.about_tab, text="说明")

        self._build_backup_tab()
        self._build_restore_tab()
        self._build_about_tab()

        footer = ttk.Frame(self)
        footer.pack(fill="x", padx=12, pady=(0, 12))
        self.progress = ttk.Progressbar(footer, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(footer, textvariable=self.status_var, width=32).pack(side="right", padx=(10, 0))

    def _build_backup_tab(self) -> None:
        tab = self.backup_tab
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(6, weight=1)

        ttk.Label(tab, text="创建 Codex 对话记录备份", style="Header.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")

        self.codex_home_var = tk.StringVar(value=str(default_codex_home()))
        self.output_var = tk.StringVar(value=str(default_backup_dir() / default_backup_name()))
        self.include_logs_var = tk.BooleanVar(value=True)
        self.include_config_var = tk.BooleanVar(value=False)
        self.include_appdata_var = tk.BooleanVar(value=False)
        self.include_sensitive_var = tk.BooleanVar(value=False)

        self._path_row(tab, 1, "Codex 用户目录", self.codex_home_var, self._browse_codex_home)
        self._path_row(tab, 2, "备份包输出", self.output_var, self._browse_backup_output, save=True)

        options = ttk.Frame(tab)
        options.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 6))
        ttk.Checkbutton(options, text="包含运行日志 SQLite", variable=self.include_logs_var).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(options, text="包含配置/技能/插件", variable=self.include_config_var).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(options, text="包含桌面端 AppData", variable=self.include_appdata_var).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(
            options,
            text="包含敏感登录文件",
            variable=self.include_sensitive_var,
            style="Danger.TCheckbutton",
        ).pack(side="left")

        actions = ttk.Frame(tab)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 10))
        ttk.Button(actions, text="扫描预览", command=self.scan_backup).pack(side="left")
        ttk.Button(actions, text="开始备份", command=self.start_backup, style="Accent.TButton").pack(side="left", padx=(8, 0))

        ttk.Label(tab, text="预览与日志", style="Muted.TLabel").grid(row=5, column=0, columnspan=3, sticky="w")
        self.backup_text = self._text_box(tab)
        self.backup_text.grid(row=6, column=0, columnspan=3, sticky="nsew")

    def _build_restore_tab(self) -> None:
        tab = self.restore_tab
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(7, weight=1)

        ttk.Label(tab, text="恢复到当前账号或新账号", style="Header.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")

        self.restore_backup_var = tk.StringVar()
        self.target_home_var = tk.StringVar(value=str(default_codex_home()))
        self.restore_mode_var = tk.StringVar(value="merge")
        self.restore_appdata_var = tk.BooleanVar(value=False)
        self.snapshot_var = tk.BooleanVar(value=True)

        self._path_row(tab, 1, "备份包", self.restore_backup_var, self._browse_restore_backup)
        self._path_row(tab, 2, "目标 Codex 目录", self.target_home_var, self._browse_target_home)

        modes = ttk.Frame(tab)
        modes.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 6))
        ttk.Radiobutton(modes, text="合并，不覆盖已有文件", variable=self.restore_mode_var, value="merge").pack(side="left", padx=(0, 14))
        ttk.Radiobutton(modes, text="覆盖恢复", variable=self.restore_mode_var, value="overwrite").pack(side="left", padx=(0, 14))
        ttk.Checkbutton(modes, text="恢复前自动快照", variable=self.snapshot_var).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(modes, text="恢复 AppData", variable=self.restore_appdata_var).pack(side="left")

        actions = ttk.Frame(tab)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 10))
        ttk.Button(actions, text="读取备份包", command=self.inspect_backup).pack(side="left")
        ttk.Button(actions, text="快速校验", command=self.quick_verify).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="开始恢复", command=self.start_restore, style="Accent.TButton").pack(side="left", padx=(8, 0))

        hint = "恢复前建议关闭 Codex 桌面端和 CLI；覆盖恢复会替换目标端同名 SQLite 和记录文件。"
        ttk.Label(tab, text=hint, style="Muted.TLabel").grid(row=5, column=0, columnspan=3, sticky="w")

        ttk.Label(tab, text="备份包信息与恢复日志", style="Muted.TLabel").grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.restore_text = self._text_box(tab)
        self.restore_text.grid(row=7, column=0, columnspan=3, sticky="nsew")

    def _build_about_tab(self) -> None:
        tab = self.about_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        text_frame = self._text_box(tab)
        text_frame.grid(row=0, column=0, sticky="nsew")
        self._set_text(
            text_frame,
            "\n".join(
                [
                    "工具定位",
                    "  备份 Codex 本地对话记录、附件、索引和 SQLite 状态库，适合换账号、账号失效风险、换成 API 登录或迁移到新机器前使用。",
                    "",
                    "默认备份内容",
                    "  sessions / archived_sessions / session_index.jsonl / attachments / generated_images",
                    "  state_*.sqlite / goals_*.sqlite / memories_*.sqlite / logs_*.sqlite",
                    "",
                    "安全策略",
                    "  默认不备份 auth.json、cap_sid、cookies、Local Storage 等登录态数据。",
                    "  恢复时默认合并，不覆盖已有记录；覆盖恢复前会自动生成快照。",
                    "",
                    "打包方式",
                    "  先运行 build.ps1 生成 Nuitka standalone 目录。",
                    "  再运行 installer\\build-installer.ps1 调用 Inno Setup 生成安装包。",
                ]
            ),
        )
        text_frame.text.configure(state="disabled")  # type: ignore[attr-defined]

    def _path_row(self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar, command, save: bool = False) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=8, pady=5)
        ttk.Button(parent, text="选择", command=command).grid(row=row, column=2, sticky="e", pady=5)

    def _text_box(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        text = tk.Text(frame, wrap="word", height=18, borderwidth=1, relief="solid", font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        frame.text = text  # type: ignore[attr-defined]
        return frame

    def _set_text(self, text_frame: ttk.Frame, content: str) -> None:
        text = text_frame.text  # type: ignore[attr-defined]
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("end", content)
        text.see("end")

    def _append_text(self, text_frame: ttk.Frame, content: str) -> None:
        text = text_frame.text  # type: ignore[attr-defined]
        text.configure(state="normal")
        text.insert("end", content + "\n")
        text.see("end")

    def _backup_options(self) -> BackupOptions:
        return BackupOptions(
            codex_home=Path(self.codex_home_var.get()).expanduser(),
            output_path=Path(self.output_var.get()).expanduser(),
            include_logs=self.include_logs_var.get(),
            include_config=self.include_config_var.get(),
            include_appdata=self.include_appdata_var.get(),
            include_sensitive=self.include_sensitive_var.get(),
        )

    def _restore_options(self) -> RestoreOptions:
        return RestoreOptions(
            backup_path=Path(self.restore_backup_var.get()).expanduser(),
            target_codex_home=Path(self.target_home_var.get()).expanduser(),
            mode=self.restore_mode_var.get(),  # type: ignore[arg-type]
            include_appdata=self.restore_appdata_var.get(),
            create_snapshot=self.snapshot_var.get(),
        )

    def _browse_codex_home(self) -> None:
        path = filedialog.askdirectory(initialdir=self.codex_home_var.get() or str(Path.home()))
        if path:
            self.codex_home_var.set(path)

    def _browse_backup_output(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".codexbackup",
            filetypes=[("Codex 备份包", "*.codexbackup"), ("ZIP", "*.zip"), ("所有文件", "*.*")],
            initialfile=default_backup_name(),
            initialdir=str(default_backup_dir()),
        )
        if path:
            self.output_var.set(path)

    def _browse_restore_backup(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("Codex 备份包", "*.codexbackup"), ("ZIP", "*.zip"), ("所有文件", "*.*")],
            initialdir=str(default_backup_dir()),
        )
        if path:
            self.restore_backup_var.set(path)

    def _browse_target_home(self) -> None:
        path = filedialog.askdirectory(initialdir=self.target_home_var.get() or str(Path.home()))
        if path:
            self.target_home_var.set(path)

    def scan_backup(self) -> None:
        plan = create_backup_plan(self._backup_options())
        self._set_text(self.backup_text, summarize_plan(plan))
        self.status_var.set(f"扫描完成: {plan.file_count} 个文件，{format_bytes(plan.source_size)}")

    def inspect_backup(self) -> None:
        try:
            manifest = load_manifest(Path(self.restore_backup_var.get()).expanduser())
            self._set_text(self.restore_text, summarize_manifest(manifest))
            self.status_var.set("备份包已读取")
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))

    def quick_verify(self) -> None:
        path = Path(self.restore_backup_var.get()).expanduser()
        result = verify_backup(path)
        self._append_text(self.restore_text, result.message)
        self.status_var.set("校验完成" if result.ok else "校验失败")
        if not result.ok:
            messagebox.showerror("校验失败", result.message)

    def _run_background(self, label: str, worker) -> None:
        if self.active_thread and self.active_thread.is_alive():
            messagebox.showinfo("正在执行", "已有任务正在运行。")
            return
        self.progress.configure(value=0, maximum=100)
        self.status_var.set(label)
        self.active_thread = threading.Thread(target=worker, daemon=True)
        self.active_thread.start()

    def start_backup(self) -> None:
        options = self._backup_options()
        if options.include_sensitive:
            ok = messagebox.askyesno("确认敏感文件", "你选择了备份登录/设备相关文件。请确认备份包只保存到可信位置。")
            if not ok:
                return

        def worker() -> None:
            result = create_backup(options, lambda m, d, t: self.queue.put(("progress", (m, d, t))))
            self.queue.put(("backup_result", result))

        self._set_text(self.backup_text, "开始备份...\n")
        self._run_background("备份中", worker)

    def start_restore(self) -> None:
        options = self._restore_options()
        if options.mode == "overwrite":
            ok = messagebox.askyesno("确认覆盖恢复", "覆盖恢复会替换目标端同名记录文件和 SQLite。建议先关闭 Codex。继续吗？")
            if not ok:
                return

        def worker() -> None:
            result = restore_backup(options, lambda m, d, t: self.queue.put(("progress", (m, d, t))))
            self.queue.put(("restore_result", result))

        self._append_text(self.restore_text, "开始恢复...")
        self._run_background("恢复中", worker)

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    message, done, total = payload  # type: ignore[misc]
                    maximum = max(int(total), 1)
                    self.progress.configure(maximum=maximum, value=int(done))
                    self.status_var.set(str(message))
                elif kind == "backup_result":
                    result = payload
                    self._append_text(self.backup_text, result.message)
                    if result.details:
                        self._append_text(
                            self.backup_text,
                            f"文件 {result.details.get('files', 0)} 个，备份包 {format_bytes(int(result.details.get('archive_size', 0)))}",
                        )
                    for warning in result.warnings:
                        self._append_text(self.backup_text, "警告: " + warning)
                    self.status_var.set("备份完成" if result.ok else "备份失败")
                    if not result.ok:
                        messagebox.showerror("备份失败", result.message)
                elif kind == "restore_result":
                    result = payload
                    self._append_text(self.restore_text, result.message)
                    if result.details:
                        self._append_text(self.restore_text, str(result.details))
                    for warning in result.warnings:
                        self._append_text(self.restore_text, "警告: " + warning)
                    self.status_var.set("恢复完成" if result.ok else "恢复失败")
                    if not result.ok:
                        messagebox.showerror("恢复失败", result.message)
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)


def run() -> None:
    app = CodexMigratorApp()
    app.mainloop()
