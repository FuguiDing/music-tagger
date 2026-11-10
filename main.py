# -*- coding: utf-8 -*-
"""程序入口。"""

import os
import sys
import traceback


def _enable_dpi():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)   # 每显示器 DPI 感知
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _app_dir():
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    d = os.path.join(base, "MusicTagger")
    os.makedirs(d, exist_ok=True)
    return d


def main():
    _enable_dpi()
    try:
        from mtcore.app import App
        app = App()
        app.mainloop()
    except Exception:  # noqa: BLE001
        err = traceback.format_exc()
        log = os.path.join(_app_dir(), "crash.log")
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 60 + "\n" + err)
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("启动失败", f"程序发生错误，日志已写入：\n{log}\n\n{err[-800:]}")
            r.destroy()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        sys.path.insert(0, os.path.dirname(sys.executable))
    main()
