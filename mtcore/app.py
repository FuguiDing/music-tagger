# -*- coding: utf-8 -*-
"""音乐标签助手 —— 界面主程序。"""

import csv
import os
import queue
import threading
import time
import tkinter as tk
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import fingerprint as fpm
from . import media, pipeline
from .models import (STATUS_EXISTS, STATUS_FAILED, STATUS_MANUAL, STATUS_MATCHING,
                     STATUS_PENDING, STATUS_READY, STATUS_SKIPPED, STATUS_WRITTEN,
                     Candidate, Row, TrackFile)
from .textutil import format_duration, similarity

APP_TITLE = "音乐标签助手 · 网易云 / QQ音乐元数据匹配"
ACCENT = "#2f6fed"
BG = "#f4f6f9"
CARD = "#ffffff"
BORDER = "#dfe3e8"
TEXT = "#1f2329"
SUBTEXT = "#6b7280"
GREEN = "#15803d"
ORANGE = "#c2410c"
RED = "#b91c1c"
GRAY = "#6b7280"

COLUMNS = [
    ("idx", "#", 46, "center"),
    ("file", "文件名", 320, "w"),
    ("dur", "时长", 62, "center"),
    ("cur", "当前标签", 230, "w"),
    ("src", "来源", 72, "center"),
    ("mtitle", "匹配歌名", 210, "w"),
    ("martist", "匹配歌手", 150, "w"),
    ("malbum", "专辑", 170, "w"),
    ("score", "相似度", 72, "center"),
    ("status", "状态", 120, "center"),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(1080, 640)
        self.configure(bg=BG)
        self._set_icon()

        self.q = queue.Queue()
        self.rows = []
        self.registry = None
        self.backup = media.BackupSession()
        self.backup_lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.busy = False
        self.sort_key = None
        self.sort_desc = True

        self.var_folder = tk.StringVar(value="")
        self.var_recursive = tk.BooleanVar(value=True)
        self.var_netease = tk.BooleanVar(value=True)
        self.var_qq = tk.BooleanVar(value=True)
        self.var_cover = tk.BooleanVar(value=True)
        self.var_lyrics = tk.BooleanVar(value=False)
        self.var_overwrite = tk.BooleanVar(value=True)
        self.var_rename = tk.BooleanVar(value=False)
        self.var_auto = tk.BooleanVar(value=True)
        self.var_skip_tagged = tk.BooleanVar(value=False)
        self.var_threshold = tk.DoubleVar(value=0.82)
        self.var_workers = tk.IntVar(value=3)
        self.var_template = tk.StringVar(value="{artist} - {title}")
        self.var_status = tk.StringVar(value="就绪")
        # 声纹兜底
        self.var_acoustic = tk.BooleanVar(value=True)
        self.var_eng_acoustid = tk.BooleanVar(value=True)
        self.var_eng_shazam = tk.BooleanVar(value=True)
        self.var_acoustid_key = tk.StringVar(value=fpm.DEFAULT_API_KEY)
        self.var_acoustic_hint = tk.StringVar(value="")

        self._build_style()
        self._build_ui()
        self._fit_window()
        self.after(80, self._pump)
        self.after(400, self._announce_acoustic)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _fit_window(self):
        """按内容自适应窗口大小，并居中（兼容高 DPI 缩放）。"""
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(max(self.winfo_reqwidth() + 28, 1120), sw - 60)
        h = min(max(self.winfo_reqheight() + 40, 700), sh - 80)
        self.geometry(f"{int(w)}x{int(h)}+{max((sw - int(w)) // 2, 0)}+{max((sh - int(h)) // 3, 0)}")

    # ------------------------------------------------------------------ 样式
    def _set_icon(self):
        """设置窗口图标（macOS 的 Tk 不支持 .ico，改用 iconphoto）。"""
        try:
            import sys
            base = Path(getattr(__import__("sys"), "_MEIPASS",
                                Path(__file__).resolve().parent.parent))
            candidates = [base, base / "assets"]

            if sys.platform == "darwin":
                from tkinter import PhotoImage
                for d in candidates:
                    png = d / "icon_256.png"
                    if png.exists():
                        self.iconphoto(True, PhotoImage(file=str(png)))
                        return
                return

            for d in candidates:
                ico = d / "icon.ico"
                if ico.exists():
                    self.iconbitmap(str(ico))
                    return
        except Exception:
            pass

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        f = "Microsoft YaHei UI"
        style.configure(".", font=(f, 10), background=BG, foreground=TEXT)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD, relief="flat")
        style.configure("TLabel", background=BG, foreground=TEXT, font=(f, 10))
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=(f, 10))
        style.configure("Sub.TLabel", background=BG, foreground=SUBTEXT, font=(f, 9))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=(f, 16, "bold"))
        style.configure("H1.TLabel", background=CARD, foreground=TEXT, font=(f, 13, "bold"))
        style.configure("H2.TLabel", background=CARD, foreground=TEXT, font=(f, 10, "bold"))
        style.configure("CardSub.TLabel", background=CARD, foreground=SUBTEXT, font=(f, 9))
        style.configure("TCheckbutton", background=BG, font=(f, 10))
        style.configure("Card.TCheckbutton", background=CARD, font=(f, 10))
        style.configure("TButton", font=(f, 10), padding=(12, 6))
        style.configure("Accent.TButton", font=(f, 10, "bold"), padding=(14, 7),
                        background=ACCENT, foreground="#ffffff", borderwidth=0)
        style.map("Accent.TButton",
                  background=[("active", "#1d5bd8"), ("disabled", "#a8bdea")],
                  foreground=[("disabled", "#f0f0f0")])
        style.configure("TEntry", fieldbackground="#ffffff", bordercolor=BORDER, padding=4)
        style.configure("TSpinbox", fieldbackground="#ffffff", padding=3)
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff",
                        foreground=TEXT, rowheight=27, font=(f, 9), borderwidth=0)
        style.configure("Treeview.Heading", font=(f, 9, "bold"), background="#eef1f6",
                        foreground="#374151", padding=(6, 7), relief="flat")
        style.map("Treeview.Heading", background=[("active", "#e2e7ef")])
        style.map("Treeview", background=[("selected", "#dbe7ff")],
                  foreground=[("selected", "#10254a")])
        style.configure("TProgressbar", background=ACCENT, troughcolor="#e6eaf1", thickness=8)
        style.configure("TSeparator", background=BORDER)

    # ------------------------------------------------------------------ 布局
    def _build_ui(self):
        outer = ttk.Frame(self, padding=(14, 12, 14, 8))
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(fill="x", pady=(0, 8))
        ttk.Label(head, text="音乐标签助手", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="  无损音乐元数据批量匹配 · 网易云 / QQ音乐",
                  style="Sub.TLabel").pack(side="left", padx=(4, 0), pady=(6, 0))

        # --- 目录行 ---
        row1 = ttk.Frame(outer)
        row1.pack(fill="x", pady=(0, 6))
        ttk.Label(row1, text="音乐目录").pack(side="left", padx=(0, 8))
        self.ent_folder = ttk.Entry(row1, textvariable=self.var_folder)
        self.ent_folder.pack(side="left", fill="x", expand=True)
        ttk.Checkbutton(row1, text="包含子文件夹", variable=self.var_recursive,
                        command=self.start_scan).pack(side="left", padx=(8, 0))
        ttk.Button(row1, text="浏览…", command=self.choose_folder).pack(side="left", padx=6)
        ttk.Button(row1, text="扫描", style="Accent.TButton",
                   command=self.start_scan).pack(side="left")

        # --- 选项行 ---
        opt = ttk.Frame(outer)
        opt.pack(fill="x", pady=(0, 8))
        ttk.Label(opt, text="音源").pack(side="left", padx=(0, 6))
        ttk.Checkbutton(opt, text="网易云", variable=self.var_netease).pack(side="left")
        ttk.Checkbutton(opt, text="QQ音乐", variable=self.var_qq).pack(side="left", padx=(6, 14))

        ttk.Label(opt, text="写入内容").pack(side="left", padx=(0, 6))
        ttk.Checkbutton(opt, text="封面", variable=self.var_cover).pack(side="left")
        ttk.Checkbutton(opt, text="歌词", variable=self.var_lyrics).pack(side="left", padx=(6, 14))

        ttk.Label(opt, text="自动写入阈值").pack(side="left")
        ttk.Spinbox(opt, from_=0.5, to=1.0, increment=0.02, width=5,
                    textvariable=self.var_threshold, format="%.2f").pack(side="left", padx=(6, 4))
        ttk.Checkbutton(opt, text="匹配后自动写入", variable=self.var_auto).pack(side="left", padx=(0, 14))

        ttk.Label(opt, text="并发").pack(side="left")
        ttk.Spinbox(opt, from_=1, to=8, width=3, textvariable=self.var_workers).pack(side="left", padx=(6, 14))

        # --- 第二选项行 ---
        opt2 = ttk.Frame(outer)
        opt2.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(opt2, text="覆盖已有标签", variable=self.var_overwrite).pack(side="left")
        ttk.Checkbutton(opt2, text="重命名文件", variable=self.var_rename).pack(side="left", padx=(14, 0))
        ttk.Entry(opt2, textvariable=self.var_template, width=26).pack(side="left", padx=(6, 10))
        ttk.Label(opt2, text="可用变量：{artist} {title} {album} {track}", style="Sub.TLabel").pack(side="left")
        ttk.Checkbutton(opt2, text="跳过标签完整的文件", variable=self.var_skip_tagged).pack(side="left", padx=(16, 0))

        # --- 操作按钮 ---
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(0, 8))
        self.btn_match = ttk.Button(bar, text="开始匹配", style="Accent.TButton", command=self.start_match)
        self.btn_match.pack(side="left")
        self.btn_stop = ttk.Button(bar, text="停止", command=self.stop_all, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        ttk.Button(bar, text="应用选中", command=self.apply_selected).pack(side="left")
        ttk.Button(bar, text="应用全部高置信", command=self.apply_all).pack(side="left", padx=6)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(bar, text="撤销写入", command=self.show_undo).pack(side="left")
        ttk.Button(bar, text="导出报告", command=self.export_report).pack(side="left", padx=6)
        ttk.Button(bar, text="音源检测", command=self.check_sources).pack(side="left")
        # --- 右侧：声纹兜底
        ttk.Button(bar, text="声纹设置", command=self.show_acoustic_settings).pack(side="right")
        ttk.Checkbutton(bar, text="声纹兜底", variable=self.var_acoustic,
                        command=self._refresh_acoustic_hint).pack(side="right", padx=(0, 8))

        # --- 表格 ---
        table_box = ttk.Frame(outer, style="Card.TFrame", padding=1)
        table_box.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table_box, columns=[c[0] for c in COLUMNS],
                                 show="headings", selectmode="extended")
        for key, label, width, anchor in COLUMNS:
            self.tree.heading(key, text=label, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key in ("file", "cur", "mtitle", "malbum")))
        vsb = ttk.Scrollbar(table_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background="#fbfcfe")
        self.tree.tag_configure("even", background="#ffffff")
        self.tree.tag_configure("ok", foreground=GREEN)
        self.tree.tag_configure("warn", foreground=ORANGE)
        self.tree.tag_configure("bad", foreground=RED)
        self.tree.tag_configure("muted", foreground=GRAY)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<Button-3>", self.on_right_click)

        # --- 底部 ---
        foot = ttk.Frame(outer)
        foot.pack(fill="x", pady=(8, 0))
        self.pbar = ttk.Progressbar(foot, mode="determinate", maximum=100)
        self.pbar.pack(side="left", fill="x", expand=True)
        ttk.Label(foot, textvariable=self.var_status, style="Sub.TLabel",
                  width=46, anchor="e").pack(side="left", padx=(12, 0))

        log_frame = ttk.Frame(outer, style="Card.TFrame", padding=1)
        log_frame.pack(fill="x", pady=(8, 0))
        self.log = tk.Text(log_frame, height=5, bg="#ffffff", fg="#374151", bd=0,
                           font=("Consolas", 9), wrap="word", padx=8, pady=6)
        self.log.pack(side="left", fill="both", expand=True)
        lsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set, state="disabled")
        lsb.pack(side="right", fill="y")
        self.log.tag_configure("err", foreground=RED)
        self.log.tag_configure("ok", foreground=GREEN)
        self.log.tag_configure("dim", foreground=GRAY)

        self.menu = tk.Menu(self, tearoff=0, font=("Microsoft YaHei UI", 9))
        self.menu.add_command(label="重新匹配此文件", command=lambda: self.rematch_selected())
        self.menu.add_command(label="手动搜索 / 更换匹配", command=lambda: self.on_double_click(None))
        self.menu.add_separator()
        self.menu.add_command(label="在资源管理器中显示", command=self.open_location)
        self.menu.add_command(label="标记为跳过", command=self.mark_skip)

    # ------------------------------------------------------------------ 工具
    def log_line(self, msg, level="info"):
        ts = time.strftime("%H:%M:%S")
        self.log.configure(state="normal")
        tag = {"error": "err", "ok": "ok", "dim": "dim"}.get(level, "")
        self.log.insert("end", f"[{ts}] {msg}\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")
        # 限制日志长度
        if int(self.log.index("end-1c").split(".")[0]) > 400:
            self.log.configure(state="normal")
            self.log.delete("1.0", "150.0")
            self.log.configure(state="disabled")

    def set_busy(self, busy: bool):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.btn_match.configure(state=state)
        self.btn_stop.configure(state="normal" if busy else "disabled")

    def options(self) -> pipeline.Options:
        engines = []
        if self.var_eng_acoustid.get():
            engines.append("acoustid")
        if self.var_eng_shazam.get():
            engines.append("shazam")
        return pipeline.Options(
            use_netease=self.var_netease.get(),
            use_qq=self.var_qq.get(),
            download_cover=self.var_cover.get(),
            download_lyrics=self.var_lyrics.get(),
            overwrite=self.var_overwrite.get(),
            rename=self.var_rename.get(),
            rename_template=self.var_template.get() or "{artist} - {title}",
            threshold=float(self.var_threshold.get() or 0.82),
            auto_write=self.var_auto.get(),
            workers=max(1, int(self.var_workers.get() or 3)),
            use_acoustic=self.var_acoustic.get(),
            acoustic_engines=tuple(engines) or ("acoustid",),
            acoustid_key=self.var_acoustid_key.get().strip() or fpm.DEFAULT_API_KEY,
        )

    # ------------------------------------------------------- 声纹设置对话框
    def _announce_acoustic(self):
        """启动时在日志区报告声纹通道可用性。"""
        self._refresh_acoustic_hint()
        if not self.var_acoustic.get():
            return
        st = fpm.engine_status()
        self.log_line(
            f"声纹兜底：AcoustID {st.get('acoustid', '?')}；Shazam {st.get('shazam', '?')}",
            "dim")

    def _refresh_acoustic_hint(self):
        if not self.var_acoustic.get():
            self.var_acoustic_hint.set("声纹：已关闭")
            return
        st = fpm.engine_status()
        parts = []
        if self.var_eng_acoustid.get():
            parts.append(f"AcoustID {st.get('acoustid', '')}")
        if self.var_eng_shazam.get():
            parts.append(f"Shazam {st.get('shazam', '')}")
        self.var_acoustic_hint.set("声纹：" + "；".join(parts))

    def show_acoustic_settings(self):
        win = tk.Toplevel(self)
        win.title("声纹兜底设置")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        try:
            win.iconphoto(False, self.icon_image) if hasattr(self, "icon_image") else None
        except Exception:
            pass
        box = ttk.Frame(win, style="Card.TFrame", padding=18)
        box.pack(fill="both", expand=True, padx=14, pady=14)

        ttk.Label(box, text="声纹兜底通道", style="H1.TLabel").pack(anchor="w")
        ttk.Label(box, text="当文件名/标签无法确认歌曲时，用音频指纹直接识别，"
                            "再把识别结果回查网易云、QQ音乐补全专辑、封面与歌词。",
                  style="CardSub.TLabel", wraplength=520).pack(anchor="w", pady=(4, 12))

        st = fpm.engine_status()
        f1 = ttk.Frame(box, style="Card.TFrame")
        f1.pack(fill="x", pady=(0, 6))
        ttk.Checkbutton(f1, text="AcoustID（Chromaprint 指纹）",
                        variable=self.var_eng_acoustid).pack(side="left")
        ttk.Label(f1, text=f"  {st.get('acoustid', '')}", style="CardSub.TLabel").pack(side="left")

        f2 = ttk.Frame(box, style="Card.TFrame")
        f2.pack(fill="x", pady=(0, 6))
        ttk.Checkbutton(f2, text="Shazam（多段采样投票）",
                        variable=self.var_eng_shazam).pack(side="left")
        ttk.Label(f2, text=f"  {st.get('shazam', '')}", style="CardSub.TLabel").pack(side="left")

        ttk.Separator(box).pack(fill="x", pady=12)

        ttk.Label(box, text="AcoustID 客户端密钥").pack(anchor="w")
        row = ttk.Frame(box, style="Card.TFrame")
        row.pack(fill="x", pady=(4, 2))
        ttk.Entry(row, textvariable=self.var_acoustid_key, width=34).pack(side="left")
        ttk.Label(row, text="  可在 acoustid.org/new-application 免费申请",
                  style="CardSub.TLabel").pack(side="left")

        ttk.Label(box, text="说明", style="H2.TLabel").pack(anchor="w", pady=(14, 4))
        tips = (
            "· AcoustID 免费、稳定，欧美曲库覆盖好；华语流行命中率偏低。\n"
            "· Shazam 华语覆盖极好，但为非官方接口，连续大量识别可能被限流，"
            "届时自动暂停 5 分钟后恢复。\n"
            "· 声纹每首约 2~10 秒（Live 专辑、长前奏会更久），只在文本匹配"
            "置信度不足时才触发，不会拖慢整批任务。\n"
            "· 识别结果仍会用文本相似度回查音源二次校验，防止误识别被写入。"
        )
        ttk.Label(box, text=tips, style="CardSub.TLabel", justify="left").pack(anchor="w")

        bar = ttk.Frame(box, style="Card.TFrame")
        bar.pack(fill="x", pady=(16, 0))
        ttk.Button(bar, text="关闭", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton", command=lambda: (
            self._refresh_acoustic_hint(), win.destroy())).pack(side="right", padx=6)

        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.grab_set()

    # ------------------------------------------------------------------ 扫描
    def choose_folder(self):
        d = filedialog.askdirectory(title="选择音乐文件夹")
        if d:
            self.var_folder.set(d)
            self.start_scan()

    def start_scan(self):
        folder = self.var_folder.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("提示", "请先选择一个存在的音乐文件夹。")
            return
        if self.busy:
            return
        self.tree.delete(*self.tree.get_children())
        self.rows = []
        self.set_busy(True)
        self.var_status.set("正在扫描…")
        self.pbar.configure(mode="determinate", value=0, maximum=100)
        self.log_line(f"扫描目录：{folder}", "dim")
        rec = self.var_recursive.get()
        skip_tagged = self.var_skip_tagged.get()

        def work():
            try:
                def prog(i, total, name):
                    self.q.put(("scan_progress", i, total, name))
                tracks = media.scan_folder(folder, rec, on_progress=prog,
                                           should_stop=self.stop_flag.is_set)
                self.q.put(("scan_done", tracks, skip_tagged))
            except Exception as e:  # noqa: BLE001
                self.q.put(("fatal", f"扫描失败：{e}"))

        threading.Thread(target=work, daemon=True).start()

    def on_scan_done(self, tracks, skip_tagged):
        self.rows = []
        self.tree.delete(*self.tree.get_children())
        for i, t in enumerate(tracks):
            row = Row(track=t)
            if t.error:
                row.status = STATUS_FAILED
                row.note = t.error
            elif skip_tagged and t.tag_title and t.tag_artist and t.tag_album and t.has_cover:
                row.status = STATUS_EXISTS
                row.note = "标签完整"
            self.rows.append(row)
            self.tree.insert("", "end", iid=str(i), values=self._values(row, i),
                             tags=self._tags_for(row, i))
        self._refresh_status()
        self.set_busy(False)
        self.pbar.configure(value=100)
        self.log_line(f"扫描完成，共 {len(tracks)} 个文件。", "ok")
        if not tracks:
            self.log_line("该目录下没有找到支持的音频文件（flac/wav/mp3/m4a/ape…）。", "dim")

    def _values(self, row: Row, index: int):
        t = row.track
        cur = " / ".join([x for x in (t.display_title, t.display_artist) if x]) or "—"
        target = row.target
        status_text = row.status
        if row.note and row.status == STATUS_FAILED:
            status_text = f"{row.status}·{row.note[:10]}"
        source = target.source if target else ""
        if row.acoustic and target:
            source = f"♪{source}"   # ♪ 表示这首歌由声纹定位
        return (
            index + 1,
            t.filename,
            t.duration_text if t.duration else "--:--",
            cur,
            source,
            target.title if target else "",
            target.artists if target else "",
            target.album if target else "",
            f"{target.score * 100:.0f}%" if target else "",
            status_text,
        )

    def _tags_for(self, row: Row, index: int) -> tuple:
        base = "even" if (index % 2 == 0) else "odd"
        extra = []
        if row.status == STATUS_WRITTEN:
            extra.append("ok")
        elif row.status in (STATUS_FAILED,):
            extra.append("bad")
        elif row.status in (STATUS_EXISTS, STATUS_SKIPPED):
            extra.append("muted")
        elif row.status in (STATUS_READY, STATUS_MANUAL) and row.target:
            extra.append("ok" if row.target.score >= self.options().threshold else "warn")
        return tuple([base] + extra)

    def refresh_row(self, index: int):
        if 0 <= index < len(self.rows):
            row = self.rows[index]
            iid = str(index)
            if self.tree.exists(iid):
                self.tree.item(iid, values=self._values(row, index),
                               tags=self._tags_for(row, index))

    # ------------------------------------------------------------------ 匹配
    def start_match(self):
        if not self.rows:
            messagebox.showinfo("提示", "请先扫描音乐目录。")
            return
        if self.busy:
            return
        opts = self.options()
        if not (opts.use_netease or opts.use_qq):
            messagebox.showwarning("提示", "请至少勾选一个音源。")
            return
        targets = [i for i, r in enumerate(self.rows)
                   if r.status in (STATUS_PENDING, STATUS_FAILED, STATUS_READY, STATUS_MANUAL)]
        if not targets:
            messagebox.showinfo("提示", "没有需要匹配的文件。")
            return
        self.stop_flag.clear()
        self.set_busy(True)
        self.registry = pipeline.SourceRegistry(opts)
        self.backup = media.BackupSession()
        self.pbar.configure(mode="determinate", value=0, maximum=len(targets))
        self.var_status.set(f"匹配中 0/{len(targets)}")
        self.log_line(f"开始匹配 {len(targets)} 个文件（并发 {opts.workers}）。", "dim")
        total = len(targets)

        def work():
            done = 0
            lock = threading.Lock()
            try:
                def task(idx):
                    row = self.rows[idx]
                    if self.stop_flag.is_set():
                        return
                    self.q.put(("row_status", idx, STATUS_MATCHING))
                    res = pipeline.search_track_with_acoustic(
                        row.track, self.registry.sources(), opts)
                    best = res.best
                    self.q.put(("row_result", idx, res.candidates, res.errors,
                                res.acoustic, res.acoustic_note))
                    if best and opts.auto_write and best.score >= opts.threshold:
                        ok, msg, info = pipeline.write_track(row.track, best, self.registry, opts)
                        if ok:
                            with self.backup_lock:
                                self.backup.add(row.track.path, info.get("before", {}),
                                                info.get("changed", []),
                                                info.get("had_cover", True))
                        self.q.put(("row_written", idx, ok, msg, best))

                with ThreadPoolExecutor(max_workers=opts.workers) as ex:
                    futures = [ex.submit(task, i) for i in targets]
                    for f in futures:
                        f.result()
                        with lock:
                            done += 1
                            self.q.put(("match_progress", done, total))
            except Exception as e:  # noqa: BLE001
                self.q.put(("fatal", f"匹配中断：{e}\n{traceback.format_exc(limit=2)}"))
            finally:
                bf = self.backup.commit()
                self.q.put(("match_done", bf))

        threading.Thread(target=work, daemon=True).start()

    def on_row_result(self, idx, candidates, errors, acoustic=None, acoustic_note=""):
        if idx >= len(self.rows):
            return
        row = self.rows[idx]
        row.candidates = candidates
        row.best = candidates[0] if candidates else None
        if acoustic is not None:
            row.acoustic = f"{acoustic.engine} · {acoustic.title}/{acoustic.artists}"
        if row.status == STATUS_MATCHING or row.status in (STATUS_PENDING, STATUS_FAILED):
            if row.best:
                row.status = STATUS_MANUAL if row.manual else STATUS_READY
                if acoustic is not None:
                    self.log_line(
                        f"♪ {row.track.filename} → 声纹识别 {acoustic.title} - "
                        f"{acoustic.artists}（{acoustic.engine}，置信 {acoustic.score * 100:.0f}%）",
                        "ok")
            else:
                row.status = STATUS_FAILED
                row.note = "未找到匹配"
        for e in errors[:1]:
            self.log_line(f"{row.track.filename} → {e}", "error")
        self.refresh_row(idx)

    def on_row_written(self, idx, ok, msg, cand):
        if idx >= len(self.rows):
            return
        row = self.rows[idx]
        if ok:
            row.status = STATUS_WRITTEN
            row.written = True
            row.note = ""
            self.log_line(f"✓ {row.track.filename} ← {cand.title} - {cand.artists}（{msg}）", "ok")
            # 重新读取，更新"当前标签"列
            try:
                nt = media.read_track(row.track.path)
                nt.q_title, nt.q_artist = nt.tag_title or nt.q_title, nt.tag_artist or nt.q_artist
                row.track = nt
            except Exception:
                pass
        else:
            row.status = STATUS_FAILED
            row.note = msg
            self.log_line(f"✗ {row.track.filename}：{msg}", "error")
        self.refresh_row(idx)
        self._refresh_status()

    # ------------------------------------------------------------------ 手动应用
    def apply_selected(self):
        sel = [int(i) for i in self.tree.selection()]
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选择要写入的行（可多选）。")
            return
        todo = []
        for idx in sel:
            row = self.rows[idx]
            if row.target:
                todo.append(idx)
        if not todo:
            messagebox.showinfo("提示", "选中的行还没有匹配结果。")
            return
        self._apply_rows(todo)

    def apply_all(self):
        thr = self.options().threshold
        todo = [i for i, r in enumerate(self.rows)
                if r.target and r.status in (STATUS_READY, STATUS_MANUAL)
                and r.target.score >= thr]
        if not todo:
            messagebox.showinfo("提示", f"没有相似度 ≥ {thr:.2f} 的待写入项。")
            return
        if not messagebox.askyesno("确认写入",
                                   f"即将写入 {len(todo)} 个文件（阈值 {thr:.2f}）。\n"
                                   "写入前会自动备份原标签，可随时撤销。是否继续？"):
            return
        self._apply_rows(todo)

    def _apply_rows(self, todo):
        if self.busy:
            return
        opts = self.options()
        if self.registry is None:
            self.registry = pipeline.SourceRegistry(opts)
        self.stop_flag.clear()
        self.set_busy(True)
        self.backup = media.BackupSession()
        self.pbar.configure(mode="determinate", value=0, maximum=len(todo))
        total = len(todo)

        def work():
            done = 0
            try:
                for idx in todo:
                    if self.stop_flag.is_set():
                        break
                    row = self.rows[idx]
                    cand = row.target
                    ok, msg, info = pipeline.write_track(row.track, cand, self.registry, opts)
                    if ok:
                        with self.backup_lock:
                            self.backup.add(row.track.path, info.get("before", {}),
                                            info.get("changed", []),
                                            info.get("had_cover", True))
                    self.q.put(("row_written", idx, ok, msg, cand))
                    done += 1
                    self.q.put(("match_progress", done, total))
            except Exception as e:  # noqa: BLE001
                self.q.put(("fatal", f"写入中断：{e}"))
            finally:
                bf = self.backup.commit()
                self.q.put(("match_done", bf))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ 候选对话框
    def on_double_click(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self.rows):
            CandidateDialog(self, idx, self.rows[idx])

    def rematch_selected(self):
        sel = [int(i) for i in self.tree.selection()]
        if not sel:
            return
        opts = self.options()
        if self.registry is None:
            self.registry = pipeline.SourceRegistry(opts)

        def work():
            for idx in sel:
                row = self.rows[idx]
                self.q.put(("row_status", idx, STATUS_MATCHING))
                res = pipeline.search_track_with_acoustic(
                    row.track, self.registry.sources(), opts)
                self.q.put(("row_result", idx, res.candidates, res.errors,
                            res.acoustic, res.acoustic_note))
        threading.Thread(target=work, daemon=True).start()

    def on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            self.menu.tk_popup(event.x_root, event.y_root)

    def open_location(self):
        sel = self.tree.selection()
        if sel:
            media.open_in_explorer(self.rows[int(sel[0])].track.path)

    def mark_skip(self):
        for iid in self.tree.selection():
            idx = int(iid)
            self.rows[idx].status = STATUS_SKIPPED
            self.refresh_row(idx)
        self._refresh_status()

    # ------------------------------------------------------------------ 其他命令
    def stop_all(self):
        self.stop_flag.set()
        self.log_line("已发送停止信号，等待当前任务收尾…", "dim")

    def check_sources(self):
        def work():
            from .sources import NetEaseSource, QQSource
            for cls in (NetEaseSource, QQSource):
                s = cls()
                r = s.ping()
                self.q.put(("log", f"{s.name} 连通性：{r}", "ok" if "正常" in r else "error"))
            self.q.put(("log", "音源检测完成。", "dim"))
        self.log_line("正在检测音源连通性…", "dim")
        threading.Thread(target=work, daemon=True).start()

    def show_undo(self):
        backups = media.list_backups()
        if not backups:
            messagebox.showinfo("撤销", "没有找到写入备份记录。")
            return
        UndoDialog(self, backups)

    def export_report(self):
        if not self.rows:
            messagebox.showinfo("提示", "还没有可导出的数据。")
            return
        path = filedialog.asksaveasfilename(
            title="导出匹配报告", defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")], initialfile="匹配报告.csv")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["序号", "文件名", "路径", "时长", "原标题", "原歌手",
                            "匹配来源", "匹配歌名", "匹配歌手", "匹配专辑",
                            "发行日期", "相似度", "状态", "说明"])
                for i, r in enumerate(self.rows, 1):
                    t = r.track
                    c = r.target
                    w.writerow([i, t.filename, t.path, t.duration_text,
                                t.tag_title, t.tag_artist,
                                c.source if c else "", c.title if c else "",
                                c.artists if c else "", c.album if c else "",
                                c.release_date if c else "",
                                f"{c.score:.3f}" if c else "", r.status, r.note])
            self.log_line(f"报告已导出：{path}", "ok")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("导出失败", str(e))

    # ------------------------------------------------------------------ 事件循环
    def sort_by(self, key):
        if not self.rows:
            return
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, True

        def k(row: Row):
            t, c = row.track, row.target
            if key == "file":
                return t.filename.lower()
            if key == "dur":
                return t.duration
            if key == "cur":
                return (t.display_title or "").lower()
            if key == "src":
                return c.source if c else ""
            if key == "mtitle":
                return (c.title if c else "").lower()
            if key == "martist":
                return (c.artists if c else "").lower()
            if key == "malbum":
                return (c.album if c else "").lower()
            if key == "score":
                return c.score if c else -1
            if key == "status":
                return row.status
            return 0

        order = sorted(range(len(self.rows)), key=lambda i: k(self.rows[i]),
                       reverse=self.sort_desc)
        self.rows = [self.rows[i] for i in order]
        self.tree.delete(*self.tree.get_children())
        for new_idx, row in enumerate(self.rows):
            self.tree.insert("", "end", iid=str(new_idx),
                             values=self._values(row, new_idx),
                             tags=self._tags_for(row, new_idx))
        # 同步修改行内的 iid 引用（行在 self.rows 中的位置已变）
        self.tree.selection_remove(self.tree.selection())

    def _refresh_status(self):
        total = len(self.rows)
        written = sum(1 for r in self.rows if r.status == STATUS_WRITTEN)
        ready = sum(1 for r in self.rows if r.status in (STATUS_READY, STATUS_MANUAL))
        failed = sum(1 for r in self.rows if r.status == STATUS_FAILED)
        skipped = sum(1 for r in self.rows if r.status in (STATUS_SKIPPED, STATUS_EXISTS))
        pending = sum(1 for r in self.rows if r.status in (STATUS_PENDING, STATUS_MATCHING))
        self.var_status.set(
            f"共 {total} | 已写入 {written} | 待确认 {ready} | 待匹配 {pending} | 跳过 {skipped} | 失败 {failed}")

    def _pump(self):
        try:
            while True:
                evt = self.q.get_nowait()
                kind = evt[0]
                if kind == "scan_progress":
                    _, i, total, name = evt
                    self.pbar.configure(maximum=total, value=i)
                    self.var_status.set(f"扫描 {i}/{total}")
                elif kind == "scan_done":
                    self.on_scan_done(evt[1], evt[2])
                elif kind == "match_progress":
                    _, done, total = evt
                    self.pbar.configure(maximum=total, value=done)
                    self.var_status.set(f"处理中 {done}/{total}")
                elif kind == "row_status":
                    idx, st = evt[1], evt[2]
                    if idx < len(self.rows):
                        if self.rows[idx].status != STATUS_WRITTEN:
                            self.rows[idx].status = st
                        self.refresh_row(idx)
                elif kind == "row_result":
                    self.on_row_result(evt[1], evt[2], evt[3])
                elif kind == "row_written":
                    self.on_row_written(evt[1], evt[2], evt[3], evt[4])
                elif kind == "match_done":
                    bf = evt[1]
                    self.set_busy(False)
                    self._refresh_status()
                    self.pbar.configure(value=self.pbar["maximum"])
                    if bf:
                        self.log_line(f"本次写入已备份：{Path(bf).name}（可撤销）", "dim")
                    self.log_line("任务完成。", "ok")
                elif kind == "log":
                    self.log_line(evt[1], evt[2] if len(evt) > 2 else "info")
                elif kind == "dialog_results":
                    dlg, cands, errs = evt[1], evt[2], evt[3]
                    try:
                        dlg.set_results(cands, errs)
                    except Exception:
                        pass
                elif kind == "refresh_row":
                    self.refresh_row(evt[1])
                elif kind == "refresh_status":
                    self._refresh_status()
                elif kind == "fatal":
                    self.log_line(evt[1], "error")
                    self.set_busy(False)
        except queue.Empty:
            pass
        self.after(80, self._pump)

    def _on_close(self):
        if self.busy and not messagebox.askyesno("退出", "任务仍在进行，确定退出吗？"):
            return
        self.stop_flag.set()
        self.destroy()


# --------------------------------------------------------------------------
class CandidateDialog(tk.Toplevel):
    """手动挑选匹配结果。"""

    def __init__(self, app: App, idx: int, row: Row):
        super().__init__(app)
        self.app = app
        self.idx = idx
        self.row = row
        self.candidates = list(row.candidates)
        self.title("选择匹配结果")
        self.geometry("980x560")
        self.configure(bg=BG)
        self.transient(app)
        self.grab_set()

        info = ttk.Frame(self, padding=(14, 12, 14, 6))
        info.pack(fill="x")
        ttk.Label(info, text=row.track.filename, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        sub = f"时长 {row.track.duration_text}　当前标签：{row.track.display_title}"
        if row.track.display_artist:
            sub += f" - {row.track.display_artist}"
        if row.track.tag_album:
            sub += f"　专辑：{row.track.tag_album}"
        ttk.Label(info, text=sub, style="Sub.TLabel").pack(anchor="w", pady=(4, 0))

        bar = ttk.Frame(self, padding=(14, 4, 14, 6))
        bar.pack(fill="x")
        self.var_kw = tk.StringVar(value=f"{row.track.display_artist} {row.track.display_title}".strip())
        ent = ttk.Entry(bar, textvariable=self.var_kw)
        ent.pack(side="left", fill="x", expand=True)
        ent.bind("<Return>", lambda e: self.do_search())
        ttk.Button(bar, text="搜索", style="Accent.TButton", command=self.do_search).pack(side="left", padx=6)
        self.var_hint = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.var_hint, style="Sub.TLabel").pack(side="left", padx=6)

        box = ttk.Frame(self, padding=(14, 0, 14, 6))
        box.pack(fill="both", expand=True)
        cols = ("src", "title", "artist", "album", "dur", "score")
        self.tree = ttk.Treeview(box, columns=cols, show="headings", selectmode="browse")
        for k, label, w, a in [("src", "来源", 80, "center"), ("title", "歌名", 260, "w"),
                               ("artist", "歌手", 170, "w"), ("album", "专辑", 220, "w"),
                               ("dur", "时长", 70, "center"), ("score", "相似度", 80, "center")]:
            self.tree.heading(k, text=label)
            self.tree.column(k, width=w, anchor=a)
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.choose())
        self.tree.bind("<Return>", lambda e: self.choose())

        foot = ttk.Frame(self, padding=(14, 6, 14, 14))
        foot.pack(fill="x")
        ttk.Button(foot, text="使用选中结果", style="Accent.TButton",
                   command=self.choose).pack(side="right")
        ttk.Button(foot, text="取消", command=self.destroy).pack(side="right", padx=8)
        ttk.Button(foot, text="忽略此文件", command=self.skip).pack(side="left")

        self._fill()
        self.tree.focus_set()

    def _fill(self):
        self.tree.delete(*self.tree.get_children())
        for i, c in enumerate(self.candidates):
            self.tree.insert("", "end", iid=str(i), values=(
                c.source, c.title, c.artists, c.album,
                format_duration(c.duration),
                f"{c.score * 100:.0f}%",
            ))
        if self.candidates:
            self.tree.selection_set("0")

    def do_search(self):
        kw = self.var_kw.get().strip()
        if not kw:
            return
        self.var_hint.set("搜索中…")

        def work():
            opts = self.app.options()
            reg = self.app.registry or pipeline.SourceRegistry(opts)
            self.app.registry = reg
            res = pipeline.search_track(self.row.track, reg.sources(), 15, extra_query=kw)
            self.app.q.put(("dialog_results", self, res.candidates, res.errors))

        threading.Thread(target=work, daemon=True).start()

    def set_results(self, candidates, errors):
        self.candidates = candidates
        self._fill()
        self.var_hint.set(f"{len(candidates)} 条结果" + (f"，{errors[0]}" if errors else ""))

    def choose(self):
        sel = self.tree.selection()
        if not sel:
            return
        cand = self.candidates[int(sel[0])]
        self.row.chosen = cand
        self.row.best = cand
        self.row.manual = True
        self.row.status = STATUS_MANUAL
        self.row.note = ""
        self.app.refresh_row(self.idx)
        self.destroy()

    def skip(self):
        self.row.status = STATUS_SKIPPED
        self.app.refresh_row(self.idx)
        self.destroy()


class UndoDialog(tk.Toplevel):
    def __init__(self, app: App, backups):
        super().__init__(app)
        self.app = app
        self.backups = backups
        self.title("撤销写入")
        self.geometry("560x420")
        self.configure(bg=BG)
        self.transient(app)
        self.grab_set()

        ttk.Label(self, text="选择要还原的备份（将恢复文本标签与封面状态）",
                  font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=14, pady=(14, 6))
        box = ttk.Frame(self, padding=(14, 0))
        box.pack(fill="both", expand=True)
        self.lb = tk.Listbox(box, font=("Microsoft YaHei UI", 9), activestyle="none",
                             bd=1, relief="solid", highlightthickness=0)
        self.lb.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        for b in backups:
            try:
                import json
                data = json.loads(Path(b).read_text(encoding="utf-8"))
                n = len(data.get("records") or [])
                self.lb.insert("end", f"{b.stem.replace('undo_', '')}    共 {n} 个文件")
            except Exception:
                self.lb.insert("end", b.name)
        if backups:
            self.lb.selection_set(0)

        foot = ttk.Frame(self, padding=(14, 10, 14, 14))
        foot.pack(fill="x")
        ttk.Button(foot, text="还原此备份", style="Accent.TButton",
                   command=self.restore).pack(side="right")
        ttk.Button(foot, text="关闭", command=self.destroy).pack(side="right", padx=8)
        ttk.Button(foot, text="打开备份目录", command=lambda: media.open_in_explorer(str(media.BACKUP_DIR))).pack(side="left")

    def restore(self):
        sel = self.lb.curselection()
        if not sel:
            return
        f = self.backups[sel[0]]
        if not messagebox.askyesno("确认还原", f"将按备份 {f.name} 还原标签，继续？"):
            return
        self.app.log_line(f"开始还原：{f.name}", "dim")

        def work():
            ok, fail, errs = media.restore_backup(
                f, on_progress=lambda i, n: self.app.q.put(("log", f"还原 {i}/{n}", "dim")))
            self.app.q.put(("log", f"还原完成：成功 {ok}，失败 {fail}", "ok" if fail == 0 else "error"))
            for e in errs[:5]:
                self.app.q.put(("log", e, "error"))
            for i, row in enumerate(self.app.rows):
                try:
                    nt = media.read_track(row.track.path)
                    row.track = nt
                    if row.status == STATUS_WRITTEN:
                        row.status = STATUS_READY
                        row.written = False
                    self.app.q.put(("refresh_row", i))
                except Exception:
                    pass
            self.app.q.put(("refresh_status",))

        threading.Thread(target=work, daemon=True).start()
        self.destroy()
