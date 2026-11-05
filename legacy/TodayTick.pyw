#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TodayTick · 定时提醒
=====================
极轻量的 Windows 定时弹窗提醒：写一句描述 + 填一个时间，到点弹出置顶小窗。

单文件、零第三方依赖（仅 Python 标准库 + tkinter），数据存本地 reminders.json。
双击 TodayTick.vbs（无黑框）或 TodayTick.pyw 即可运行。
"""

import ctypes
import json
import os
import re
import socket
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import date, datetime, time, timedelta
from tkinter import messagebox

try:
    import winsound
except ImportError:  # 非 Windows 平台仅用于开发调试
    winsound = None

APP_NAME = "TodayTick"
VERSION = "1.1"
LOCK_PORT = 48733
_DATA_FILE = "reminders.json"
NO_GLASS = False  # --no-glass：关掉半透明与亚克力（显卡/远程桌面下花屏时的退路）

# ---------------------------------------------------------------- 配色
BG = "#0d0e11"          # 窗口底
SURF = "#15171c"        # 卡片
SURF_2 = "#1c1f26"      # 悬停 / 输入底
HAIR = "#23262e"        # 1px 分隔线与描边
HAIR_HI = "#333947"     # 强调描边
TEXT = "#eceef2"
DIM = "#8a919e"
FAINT = "#565c67"
ACCENT = "#8ab4ff"
ACCENT_BG = "#1b2739"
ACCENT_EDGE = "#2b3a56"
DANGER = "#ff8f8f"

# ---------------------------------------------------------------- 尺寸（逻辑像素，按 DPI 缩放）
WIN_W = 384
WIN_H = 452
PAD = 20
ROW_H = 30
# ================================================================ 纯函数部分
_DATE_WORDS = {"今天": 0, "明天": 1, "明日": 1, "后天": 2, "大后天": 3}
_RE_REL_MIN = re.compile(r"^[+＋]?\s*(\d+)\s*(?:分钟|分|min|mins?|m)$", re.I)
_RE_REL_HOUR = re.compile(r"^[+＋]?\s*(\d+(?:\.\d+)?)\s*(?:个?小时|时|hours?|hrs?|h)$", re.I)


def parse_target(raw: str, now: datetime | None = None) -> datetime:
    """把用户输入解析成具体时间点。看不懂就抛 ValueError（附中文提示）。"""
    now = now or datetime.now()
    s = (raw or "").strip()
    s = s.replace("　", " ").replace("：", ":").replace("，", " ").replace(",", " ")
    s = re.sub(r"\s+", " ", s)
    if not s:
        raise ValueError("先填一个时间")

    m = _RE_REL_MIN.match(s)
    if m:
        return (now + timedelta(minutes=int(m.group(1)))).replace(second=0, microsecond=0)
    m = _RE_REL_HOUR.match(s)
    if m:
        return (now + timedelta(minutes=int(round(float(m.group(1)) * 60)))).replace(
            second=0, microsecond=0
        )

    day: date | None = None
    rest = s

    m = re.match(r"^(今天|明天|明日|后天|大后天)\s*(.*)$", rest)
    if m:
        day = now.date() + timedelta(days=_DATE_WORDS[m.group(1)])
        rest = m.group(2)
    else:
        m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s+(.*)$", rest)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                day = date(y, mo, d)
            except ValueError:
                raise ValueError("日期不存在")
            rest = m.group(4)
        else:
            m = re.match(r"^(\d{1,2})[-/.](\d{1,2})\s+(.*)$", rest)
            if m:
                mo, d = int(m.group(1)), int(m.group(2))
                try:
                    day = date(now.year, mo, d)
                except ValueError:
                    raise ValueError("日期不存在")
                if day < now.date():  # 只写了月日且已过 → 指明年
                    try:
                        day = date(now.year + 1, mo, d)
                    except ValueError:
                        raise ValueError("日期不存在")
                rest = m.group(3)

    rest = rest.strip()
    if not rest:
        raise ValueError("缺少具体时间")

    hh = mm = ss = 0
    m = re.fullmatch(r"(\d{1,2})[:.](\d{1,2})(?::(\d{1,2}))?", rest)
    if m:
        hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    else:
        m = re.fullmatch(r"(\d{1,2})\s*[点时]\s*(?:(\d{1,2})\s*分?)?半?", rest)
        if m:
            if rest.endswith("半"):
                hh, mm = int(m.group(1)), 30
            else:
                hh, mm = int(m.group(1)), int(m.group(2) or 0)
        else:
            m = re.fullmatch(r"(\d{3,4})", rest)
            if not m:
                raise ValueError("看不懂这个时间")
            v = m.group(1).rjust(4, "0")
            hh, mm = int(v[:2]), int(v[2:])

    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        raise ValueError("时间超出范围")

    if day is None:
        cand = datetime.combine(now.date(), time(hh, mm, ss))
        if cand <= now:
            cand += timedelta(days=1)
        return cand
    return datetime.combine(day, time(hh, mm, ss))


def fmt_when(dt: datetime, now: datetime | None = None) -> str:
    """把时间点格式化成列表里显示的样子。"""
    now = now or datetime.now()
    d = dt.date()
    n = now.date()
    if d == n:
        return dt.strftime("%H:%M")
    if d == n + timedelta(days=1):
        return "明天 " + dt.strftime("%H:%M")
    if d == n + timedelta(days=2):
        return "后天 " + dt.strftime("%H:%M")
    if d.year == n.year:
        return dt.strftime("%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d %H:%M")


def fmt_left(seconds: float) -> str:
    """剩余时间的口语化表达。"""
    s = int(round(seconds))
    if s <= 0:
        return "0 秒"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h} 小时 {m} 分"
    if m:
        return f"{m} 分 {sec} 秒"
    return f"{sec} 秒"


def beep_loop(stop: threading.Event) -> None:
    """提醒音：四音一小节，反复，直到 stop 被置位。"""
    melody = ((880, 130), (1320, 130), (880, 130), (1568, 170))
    while not stop.is_set():
        for freq, dur in melody:
            if stop.is_set():
                return
            try:
                if winsound:
                    winsound.Beep(freq, dur)
                else:
                    _time.sleep(dur / 1000.0)
            except Exception:  # 没有声卡 / 被禁用
                try:
                    if winsound:
                        winsound.MessageBeep()
                except Exception:
                    pass
                _time.sleep(0.8)
        if stop.wait(1.0):
            return


def enable_dpi_awareness() -> None:
    """避免高分屏下界面糊成一片，并让任务栏用我们自己的图标。"""
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        from ctypes import windll

        windll.shell32.SetCurrentProcessExplicitAppUserModelID("TodayTick.App.1")
    except Exception:
        pass



ICON_B64 = (
    "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"
    "w//p4/P/CxzoCBggmoZUAAAAAElFTkSuQmCC"
)


# ---------------------------------------------------------------- 绘制小工具
def round_rect(cv: tk.Canvas, x1, y1, x2, y2, r=12, **kw):
    """在 Canvas 上画圆角矩形（smooth 多边形近似）。"""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1,
        x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2,
        x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return cv.create_polygon(pts, smooth=True, **kw)


def apply_glass(win: tk.Misc, tint: int = 0xC00D0E11) -> bool:
    """尝试给窗口加 DWM 亚克力模糊（Win10/11）。失败也不影响使用。"""
    if not sys.platform.startswith("win") or NO_GLASS:
        return False

    class ACCENTPOLICY(ctypes.Structure):
        _fields_ = [
            ("AccentState", ctypes.c_int),
            ("AccentFlags", ctypes.c_int),
            ("GradientColor", ctypes.c_uint),
            ("AnimationId", ctypes.c_int),
        ]

    class WCADATA(ctypes.Structure):
        _fields_ = [
            ("Attribute", ctypes.c_int),
            ("Data", ctypes.c_void_p),
            ("SizeOfData", ctypes.c_size_t),
        ]

    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
        policy = ACCENTPOLICY(4, 2, tint, 0)  # 4 = ACRYLICBLURBEHIND
        data = WCADATA(19, ctypes.cast(ctypes.byref(policy), ctypes.c_void_p), ctypes.sizeof(policy))
        user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        # Win11：圆角 + 深色边框
        for attr, value in ((33, 2), (34, 1)):
            try:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(ctypes.c_int(value)), 4)
            except Exception:
                pass
        return True
    except Exception:
        return False


class Line(tk.Entry):
    """无边框输入框，带占位符。"""

    def __init__(self, master, font, placeholder: str, ph_color: str, bg: str, fg: str = TEXT):
        super().__init__(
            master, bd=0, relief="flat", highlightthickness=0, bg=bg, fg=fg,
            insertbackground=fg, selectbackground="#2f3a4d", selectforeground=TEXT,
            font=font, disabledbackground=bg,
        )
        self._ph = placeholder
        self._ph_color = ph_color
        self._fg = fg
        self._showing = False
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self._show_placeholder()

    def _show_placeholder(self) -> None:
        if not super().get():
            self._showing = True
            self.configure(fg=self._ph_color)
            super().insert(0, self._ph)

    def _focus_in(self, _evt=None) -> None:
        if self._showing:
            self._showing = False
            super().delete(0, "end")
            self.configure(fg=self._fg)

    def _focus_out(self, _evt=None) -> None:
        if not super().get():
            self._show_placeholder()

    def value(self) -> str:
        return "" if self._showing else super().get().strip()

    def set_value(self, text: str) -> None:
        self._showing = False
        self.configure(fg=self._fg)
        super().delete(0, "end")
        if text:
            super().insert(0, text)

    def clear(self) -> None:
        self._showing = False
        super().delete(0, "end")
        self.configure(fg=self._fg)
        self._show_placeholder()


# ==================================================================== 主窗口
class TodayTick(tk.Tk):
    def __init__(self, selftest: bool = False, data_path: str | None = None):
        super().__init__()
        self.selftest = selftest
        self._alive = True
        self._items: list[dict] = []
        self._popup: tk.Toplevel | None = None
        self._popup_cv: tk.Canvas | None = None
        self._popup_border: int | None = None
        self._queue: list[dict] = []
        self._tick_job = None
        self._flash_job = None
        self._err_job = None
        self._clock_job = None
        self._beep_stop: threading.Event | None = None
        self._drag = (0, 0)
        self._sound = True
        self._family = None
        self._mono_family = None

        enable_dpi_awareness()
        self.scale = self.winfo_fpixels("1i") / 96.0
        try:
            self.tk.call("tk", "scaling", self.scale * 96 / 72)
        except Exception:
            pass

        self.title(f"{APP_NAME} · 定时提醒")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.overrideredirect(True)          # 无边框，玻璃质感
        if not NO_GLASS:
            try:
                self.attributes("-alpha", 0.96)
            except Exception:
                pass

        w, h = self.px(WIN_W), self.px(WIN_H)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = sw - w - self.px(26)
        y = sh - h - self.px(64)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self._anchor_bottom = y + h             # 自适应缩放时保持底边不动
        self._anchor_x = x

        self._apply_icon()
        self.data_path = data_path or self._resolve_data_path()
        self._load()

        self._build_ui()
        self.update_idletasks()
        apply_glass(self)

        self._tick_job = self.after(400, self._tick)
        self._clock_job = self.after(1000, self._clock)
        if not self.selftest:
            self.desc.focus_set()

    # ------------------------------------------------------------ 基础工具
    def px(self, v: float) -> int:
        return max(1, int(round(v * self.scale)))

    def font(self, size: float, weight: str | None = None):
        fam = self._family or "Microsoft YaHei UI"
        return (fam, -self.px(size), weight) if weight else (fam, -self.px(size))

    def mono(self, size: float):
        return (self._mono_family or "Consolas", -self.px(size))

    def _apply_icon(self) -> None:
        try:
            data = tk.PhotoImage(master=self, data=ICON_B64)
            self._icon = data
            self.iconphoto(True, data)
        except Exception:
            pass

    def _pick_fonts(self) -> None:
        try:
            fams = set(tkfont.families(self))
        except Exception:
            fams = set()
        self._family = next((f for f in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI") if f in fams), None)
        self._mono_family = next((f for f in ("Cascadia Mono", "Consolas", "JetBrains Mono", "Courier New") if f in fams), None)

    # ------------------------------------------------------------ 数据
    def _resolve_data_path(self) -> str:
        base = os.path.dirname(os.path.abspath(sys.argv[0] or __file__))
        cand = os.path.join(base, _DATA_FILE)
        try:
            with open(cand, "a", encoding="utf-8"):
                pass
            return cand
        except OSError:
            alt = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
            os.makedirs(alt, exist_ok=True)
            return os.path.join(alt, _DATA_FILE)

    def _load(self) -> None:
        self._items = []
        try:
            with open(self.data_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        self._sound = bool(data.get("sound", True))
        for raw in data.get("items", []):
            try:
                when = datetime.fromisoformat(raw["when"])
                text = str(raw.get("text", "")).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if text:
                self._items.append({"when": when.isoformat(timespec="minutes"), "text": text, "fired": bool(raw.get("fired"))})

    def _save(self) -> None:
        tmp = self.data_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": VERSION, "sound": self._sound, "items": self._items}, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.data_path)
        except OSError:
            pass

    # ------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        self._pick_fonts()
        w, h = self.px(WIN_W), self.px(WIN_H)
        self._cur_h = h
        self.cv = tk.Canvas(self, width=w, height=h, bg=BG, highlightthickness=0, bd=0)
        self.cv.place(x=0, y=0, relwidth=1, relheight=1)

        # 顶栏：标题 + 时钟 + 关闭
        self.cv.create_text(self.px(PAD), self.px(20), text=APP_NAME, anchor="w", font=self.font(11, "bold"), fill=FAINT)
        self._clock_id = self.cv.create_text(w - self.px(PAD + 24), self.px(20), text="", anchor="e", font=self.mono(10), fill=FAINT)
        self._close_id = self.cv.create_text(w - self.px(PAD - 6), self.px(20), text="✕", anchor="e", font=self.font(11), fill=FAINT, tags="close")
        self.cv.tag_bind("close", "<Enter>", lambda e: self.cv.itemconfigure("close", fill=TEXT))
        self.cv.tag_bind("close", "<Leave>", lambda e: self.cv.itemconfigure("close", fill=FAINT))
        self.cv.tag_bind("close", "<Button-1>", lambda e: self._on_close())

        # 输入卡
        self._card_id = round_rect(self.cv, self.px(PAD), self.px(42), w - self.px(PAD), self.px(132), r=self.px(14),
                                   fill=SURF, outline=HAIR, width=1)
        self.cv.create_line(self.px(PAD + 14), self.px(88), w - self.px(PAD + 14), self.px(88), fill=HAIR)

        self.desc = Line(self.cv, self.font(13), "写点什么，例如 喝水 / 交周报", DIM, bg=SURF, fg=TEXT)
        self.desc.place(x=self.px(PAD + 14), y=self.px(56), width=w - self.px(2 * PAD + 28), height=self.px(24))
        self.when = Line(self.cv, self.mono(10), "15:30", DIM, bg=SURF, fg=TEXT)
        self.when.place(x=self.px(PAD + 14), y=self.px(96), width=self.px(96), height=self.px(22))
        self._hint_id = self.cv.create_text(w - self.px(PAD + 14), self.px(107), text="", anchor="e",
                                           font=self.font(9), fill=FAINT)

        self.desc.bind("<Return>", lambda e: self.when.focus_set())
        self.when.bind("<Return>", lambda e: self._add())
        self.when.bind("<KeyRelease>", lambda e: self._update_hint())
        for ent in (self.desc, self.when):
            ent.bind("<FocusIn>", lambda e: self.cv.itemconfigure(self._card_id, outline=HAIR_HI), add="+")
            ent.bind("<FocusOut>", lambda e: self.cv.itemconfigure(self._card_id, outline=HAIR), add="+")

        # 添加按钮 + 快捷时间
        round_rect(self.cv, self.px(PAD), self.px(140), self.px(PAD + 68), self.px(168), r=self.px(14),
                   fill=ACCENT_BG, outline=ACCENT_EDGE, width=1, tags="addbtn")
        self.cv.create_text(self.px(PAD + 34), self.px(154), text="添加", font=self.font(11), fill=ACCENT, tags="addbtn")
        self.cv.tag_bind("addbtn", "<Button-1>", lambda e: self._add())
        self.cv.tag_bind("addbtn", "<Enter>", lambda e: self.cv.itemconfigure("addbtn", fill="#22314a"))
        self.cv.tag_bind("addbtn", "<Leave>", lambda e: self.cv.itemconfigure("addbtn", fill=ACCENT_BG))

        x = w - self.px(PAD)
        for label, minutes in (("明早9点", None), ("+30分", 30), ("+5分", 5)):
            tid = self.cv.create_text(x, self.px(154), text=label, anchor="e", font=self.font(10), fill=FAINT,
                                      tags=("chip", f"chip_{label}"))
            bb = self.cv.bbox(tid)
            self.cv.tag_bind(f"chip_{label}", "<Enter>", lambda e, t=tid: self.cv.itemconfigure(t, fill=ACCENT))
            self.cv.tag_bind(f"chip_{label}", "<Leave>", lambda e, t=tid: self.cv.itemconfigure(t, fill=FAINT))
            self.cv.tag_bind(f"chip_{label}", "<Button-1>", lambda e, lb=label: self._chip(lb))
            x = bb[0] - self.px(14)

        # 分组标题（出错时改用它显示提示）
        self._sec_id = self.cv.create_text(self.px(PAD), self.px(190), text="", anchor="w", font=self.font(10), fill=FAINT)

        # 列表
        list_top = self.px(202)
        list_h = h - list_top - self.px(44)
        self.list = tk.Canvas(self.cv, bg=BG, highlightthickness=0, bd=0)
        self.list.place(x=self.px(PAD - 8), y=list_top, width=w - self.px(2 * PAD - 16), height=list_h)
        self.list.bind("<MouseWheel>", self._on_wheel)

        # 底栏：提示音 / 开机自启
        self._foot_y = h - self.px(24)
        self._dot_sound = self.cv.create_oval(0, 0, 0, 0, outline="", fill=ACCENT)
        self._lbl_sound = self.cv.create_text(0, 0, text="提示音", anchor="w", font=self.font(10), fill=DIM)
        self._dot_start = self.cv.create_oval(0, 0, 0, 0, outline="", fill=HAIR)
        self._lbl_start = self.cv.create_text(0, 0, text="开机自启", anchor="w", font=self.font(10), fill=FAINT)
        self._place_toggle(self.px(PAD), "sound")
        self._place_toggle(self.px(PAD + 74), "startup")
        for tag in ("tgl_sound", "tgl_startup"):
            self.cv.tag_bind(tag, "<Button-1>", lambda e, t=tag: self._toggle_click(t))
            self.cv.tag_bind(tag, "<Enter>", lambda e, t=tag: self.cv.itemconfigure(t, fill=TEXT))
            self.cv.tag_bind(tag, "<Leave>", lambda e, t=tag: self._recolor_toggles())

        # 拖动 / 滚动
        self.cv.bind("<ButtonPress-1>", self._drag_start)
        self.cv.bind("<B1-Motion>", self._drag_move)
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Escape>", lambda e: None)

        self._refresh_startup_var()
        self._recolor_toggles()
        self._refresh_list()
        self._clock()
        self._update_hint()

    def _place_toggle(self, x: int, which: str) -> None:
        if which == "sound":
            dot, lbl, tag = self._dot_sound, self._lbl_sound, "tgl_sound"
        else:
            dot, lbl, tag = self._dot_start, self._lbl_start, "tgl_startup"
        cy = self._foot_y
        r = self.px(2.6)
        self.cv.coords(dot, x, cy - r, x + 2 * r, cy + r)
        self.cv.coords(lbl, x + 2 * r + self.px(7), cy)
        self.cv.addtag_withtag(tag, dot)
        self.cv.addtag_withtag(tag, lbl)

    def _recolor_toggles(self) -> None:
        self.cv.itemconfigure(self._dot_sound, fill=ACCENT if self._sound else HAIR)
        self.cv.itemconfigure(self._lbl_sound, fill=DIM if self._sound else FAINT)
        on = self._startup_enabled()
        self.cv.itemconfigure(self._dot_start, fill=ACCENT if on else HAIR)
        self.cv.itemconfigure(self._lbl_start, fill=DIM if on else FAINT)

    def _toggle_click(self, tag: str) -> None:
        if tag == "tgl_sound":
            self._sound = not self._sound
            self._save()
            self._recolor_toggles()
        else:
            self._on_startup_toggle()
            self._recolor_toggles()

    def _chip(self, label: str) -> None:
        self.when.set_value(label)
        self._update_hint()
        if self.desc.value():
            self._add()
        else:
            self.desc.focus_set()

    def _update_hint(self) -> None:
        """右侧小字：实时把输入的时间翻译成人话。"""
        if not self._alive:
            return
        raw = self.when.value()
        if not raw:
            self.cv.itemconfigure(self._hint_id, text="明天 9点 · +30分", fill=FAINT)
            return
        try:
            when = parse_target(raw)
        except ValueError:
            self.cv.itemconfigure(self._hint_id, text="时间没看懂", fill=DANGER)
            return
        self.cv.itemconfigure(self._hint_id, text=fmt_when(when, datetime.now()) + " 提醒", fill=ACCENT)

    def _clock(self) -> None:
        if not self._alive:
            return
        try:
            self.cv.itemconfigure(self._clock_id, text=datetime.now().strftime("%H:%M"))
        except Exception:
            return
        self._clock_job = self.after(1000, self._clock)

    # ------------------------------------------------------------ 交互
    def _drag_start(self, evt) -> None:
        hit = self.cv.find_withtag("current")
        if evt.y <= self.px(38) and self._close_id not in hit:
            self._drag = (evt.x_root - self.winfo_x(), evt.y_root - self.winfo_y())

    def _drag_move(self, evt) -> None:
        if self._drag == (0, 0):
            return
        y = evt.y_root - self._drag[1]
        self.geometry(f"+{evt.x_root - self._drag[0]}+{y}")
        self._anchor_bottom = y + self._cur_h
        self._anchor_x = evt.x_root - self._drag[0]

    def _on_wheel(self, evt) -> None:
        try:
            self.list.yview_scroll(-1 if evt.delta > 0 else 1, "units")
        except Exception:
            pass

    def _flash_err(self, msg: str) -> None:
        self.cv.itemconfigure(self._sec_id, text=msg, fill=DANGER)
        if self._err_job:
            try:
                self.after_cancel(self._err_job)
            except Exception:
                pass
        self._err_job = self.after(2600, self._clear_err)

    def _clear_err(self) -> None:
        self._err_job = None
        if self._alive:
            self.cv.itemconfigure(self._sec_id, text=self._sec_text(), fill=FAINT)

    def _sec_text(self) -> str:
        n = len(self._items)
        return "待提醒 · 0" if n == 0 else f"待提醒 · {n}"

    # ------------------------------------------------------------ 增删
    def _add(self, text: str | None = None, when: datetime | None = None) -> dict | None:
        text = (text if text is not None else self.desc.value()).strip()
        if not text:
            self._flash_err("先写一句要提醒的内容")
            self.desc.focus_set()
            return None
        raw = self.when.value()
        try:
            when = when or parse_target(raw or "09:00")
        except ValueError as exc:
            self._flash_err(str(exc))
            self.when.focus_set()
            return None
        item = {"when": when.isoformat(timespec="minutes"), "text": text, "fired": False}
        self._items.append(item)
        self._save()
        self.desc.clear()
        self.when.clear()
        self._update_hint()
        self._refresh_list()
        self.desc.focus_set()
        return item

    def _remove(self, item: dict) -> None:
        if item in self._items:
            self._items.remove(item)
            self._save()
            self._refresh_list()

    # ------------------------------------------------------------ 自适应高度
    def _target_h(self) -> int:
        n = len(self._items)
        body = self.px(60) if n == 0 else min(n, 13) * self.px(ROW_H)
        return max(self.px(300), min(self.px(620), self.px(202) + body + self.px(44)))

    def _fit_height(self) -> None:
        want = self._target_h()
        if want == self._cur_h:
            return
        w = self.px(WIN_W)
        x = self._anchor_x
        y = max(0, self._anchor_bottom - want)     # 底边不动，窗口向上/向下伸缩
        sh = self.winfo_screenheight()
        if y + want > sh:
            y = max(0, sh - want)
        self._cur_h = want
        self.geometry(f"{w}x{want}+{x}+{y}")
        self.list.place_configure(height=want - self.px(202) - self.px(44))
        self._foot_y = want - self.px(24)
        self._place_toggle(self.px(PAD), "sound")
        self._place_toggle(self.px(PAD + 74), "startup")
        self.update_idletasks()

    def _refresh_list(self) -> None:
        cv = self.list
        if cv is None:
            return
        self._fit_height()
        cv.delete("all")
        cv.yview_moveto(0)
        lw = cv.winfo_width()
        if lw < 50:
            lw = self.px(WIN_W - 2 * PAD + 16)
        row = self.px(ROW_H)
        now = datetime.now()
        items = sorted(self._items, key=lambda it: it["when"])
        if self._alive:
            self.cv.itemconfigure(self._sec_id, text=self._sec_text(), fill=FAINT)
        if not items:
            cy = cv.winfo_height() // 2 or self.px(90)
            cv.create_text(lw // 2, cy - self.px(12), text="还没有提醒", font=self.font(11), fill=FAINT, anchor="center")
            cv.create_text(lw // 2, cy + self.px(8), text="写一句、填个时间，回车即可", font=self.font(9), fill="#43474f", anchor="center")
            cv.configure(scrollregion=(0, 0, lw, cv.winfo_height()))
            return
        f_text = tkfont.Font(root=self, font=self.font(12))
        maxw = lw - self.px(74) - self.px(28)
        for i, item in enumerate(items):
            y1 = i * row
            y2 = y1 + row - self.px(4)
            cy = (y1 + y2) // 2
            tag, bgtag = f"r{i}", f"bg{i}"
            round_rect(cv, self.px(2), y1, lw - self.px(2), y2, r=self.px(8), fill=BG, outline="", tags=(tag, bgtag))
            when = datetime.fromisoformat(item["when"])
            overdue = when < now
            cv.create_text(self.px(10), cy, text=fmt_when(when, now), anchor="w", font=self.mono(9),
                           fill=DANGER if overdue else DIM, tags=(tag,))
            cv.create_text(self.px(72), cy, text=self._fit(item["text"], f_text, maxw), anchor="w",
                           font=self.font(12), fill=TEXT, tags=(tag,))
            cv.create_text(lw - self.px(10), cy, text="✕", anchor="e", font=self.font(9), fill=FAINT, tags=(tag, f"x{i}"))
            cv.tag_bind(tag, "<Enter>", lambda e, t=bgtag: cv.itemconfigure(t, fill=SURF_2))
            cv.tag_bind(tag, "<Leave>", lambda e, t=bgtag: cv.itemconfigure(t, fill=BG))
            cv.tag_bind(f"x{i}", "<Button-1>", lambda e, it=item: self._remove(it))
            cv.tag_bind(f"x{i}", "<Enter>", lambda e, x=f"x{i}": cv.itemconfigure(x, fill=TEXT))
            cv.tag_bind(f"x{i}", "<Leave>", lambda e, x=f"x{i}": cv.itemconfigure(x, fill=FAINT))
        cv.configure(scrollregion=(0, 0, lw, max(len(items) * row, cv.winfo_height())))

    def _fit(self, text: str, font: tkfont.Font, maxw: int) -> str:
        if font.measure(text) <= maxw:
            return text
        s = text
        while s and font.measure(s + "…") > maxw:
            s = s[:-1]
        return s + "…"

    # ------------------------------------------------------------ 到点
    def _tick(self) -> None:
        if not self._alive:
            return
        now = datetime.now()
        due = [it for it in self._items if not it.get("fired") and datetime.fromisoformat(it["when"]) <= now]
        for it in due:
            it["fired"] = True
            self._queue.append(it)
        if due:
            self._save()
            self._refresh_list()
            self._show_next_popup()
        self._tick_job = self.after(400, self._tick)

    def _show_next_popup(self) -> None:
        if not self._alive or self._popup is not None or not self._queue:
            return
        self._build_popup(self._queue.pop(0))

    def _build_popup(self, item: dict) -> None:
        when = datetime.fromisoformat(item["when"])
        now = datetime.now()
        pw = self.px(320)
        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        if not NO_GLASS:
            try:
                win.attributes("-alpha", 0.98)
            except Exception:
                pass
        cv = tk.Canvas(win, bg=BG, highlightthickness=0, bd=0, width=pw, height=self.px(120))
        cv.pack(fill="both", expand=True)

        border = None
        cv.create_text(self.px(20), self.px(20), text=fmt_when(when, now), anchor="nw", font=self.mono(22), fill=TEXT)
        if when < now - timedelta(seconds=90):
            cv.create_text(pw - self.px(20), self.px(24), text="已过期", anchor="ne", font=self.font(9), fill=DANGER)
        desc = cv.create_text(self.px(20), self.px(58), text=item["text"], anchor="nw", width=pw - self.px(40),
                              font=self.font(12), fill=TEXT, tags="desc")
        win.update_idletasks()
        bb = cv.bbox("desc") or (0, 0, 0, self.px(30))
        dh = bb[3] - bb[1]
        ph = self.px(58) + dh + self.px(46)

        btn_h = self.px(26)
        by2 = ph - self.px(16)
        by1 = by2 - btn_h
        ok_x2 = pw - self.px(18)
        ok_x1 = ok_x2 - self.px(64)
        round_rect(cv, ok_x1, by1, ok_x2, by2, r=self.px(13), fill=ACCENT_BG, outline=ACCENT_EDGE, width=1, tags="ok")
        cv.create_text((ok_x1 + ok_x2) // 2, (by1 + by2) // 2, text="知道了", font=self.font(10), fill=ACCENT, tags="ok")
        cv.create_text(ok_x1 - self.px(20), (by1 + by2) // 2, text="稍后 5 分钟", anchor="e", font=self.font(10),
                       fill=DIM, tags="later")

        cv.configure(width=pw, height=ph)
        border = round_rect(cv, 1, 1, pw - 1, ph - 1, r=self.px(16), fill=SURF,
                            outline=ACCENT_EDGE, width=self.px(1.3), tags="pop")
        cv.tag_lower("pop")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = (sw - pw) // 2
        y = int(sh * 0.28)
        win.geometry(f"{pw}x{ph}+{x}+{y}")
        win.update_idletasks()
        apply_glass(win, 0xF00D0E11)

        self._popup = win
        self._popup_cv = cv
        self._popup_border = border
        cv.tag_bind("ok", "<Button-1>", lambda e: self._close_popup(item))
        cv.tag_bind("later", "<Button-1>", lambda e: self._close_popup(item, snooze=True))
        cv.tag_bind("ok", "<Enter>", lambda e: cv.itemconfigure("ok", fill="#22314a"))
        cv.tag_bind("ok", "<Leave>", lambda e: cv.itemconfigure("ok", fill=ACCENT_BG))
        win.bind("<Escape>", lambda e: self._close_popup(item, snooze=True))
        win.bind("<Return>", lambda e: self._close_popup(item))

        # 拖动
        state = {"off": (0, 0)}

        def press(e):
            state["off"] = (e.x_root - win.winfo_x(), e.y_root - win.winfo_y())

        def move(e):
            if state["off"] != (0, 0):
                win.geometry(f"+{e.x_root - state['off'][0]}+{e.y_root - state['off'][1]}")

        cv.bind("<ButtonPress-1>", press)
        cv.bind("<B1-Motion>", move)

        win.focus_force()
        if self._sound:
            self._start_beep()
        self._flash(win)

    def _flash(self, win: tk.Toplevel) -> None:
        if not self._alive or self._popup_cv is None:
            return
        try:
            cur = self._popup_cv.itemcget(self._popup_border, "outline")
            nxt = ACCENT if cur != ACCENT else ACCENT_EDGE
            self._popup_cv.itemconfigure(self._popup_border, outline=nxt, width=self.px(1.8) if nxt == ACCENT else self.px(1.3))
        except Exception:
            return
        self._flash_job = self.after(520, lambda: self._flash(win))

    def _start_beep(self) -> None:
        self._stop_beep()
        ev = threading.Event()
        self._beep_stop = ev
        threading.Thread(target=beep_loop, args=(ev,), daemon=True).start()

    def _stop_beep(self) -> None:
        if self._beep_stop:
            self._beep_stop.set()
            self._beep_stop = None

    def _close_popup(self, item: dict, snooze: bool = False) -> None:
        self._stop_beep()
        if self._flash_job:
            try:
                self.after_cancel(self._flash_job)
            except Exception:
                pass
            self._flash_job = None
        win, self._popup = self._popup, None
        self._popup_cv = None
        self._popup_border = None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        if snooze:
            item["when"] = (datetime.now() + timedelta(minutes=5)).isoformat(timespec="minutes")
            item["fired"] = False
        else:
            if item in self._items:
                self._items.remove(item)
        self._save()
        self._refresh_list()
        if self._queue:
            self.after(120, self._show_next_popup)

    # ------------------------------------------------------------ 开机自启
    def _startup_path(self) -> str | None:
        base = os.environ.get("APPDATA")
        if not base:
            return None
        d = os.path.join(base, r"Microsoft\Windows\Start Menu\Programs\Startup")
        return os.path.join(d, f"{APP_NAME}.vbs")

    def _startup_enabled(self) -> bool:
        p = self._startup_path()
        return bool(p) and os.path.exists(p)

    def _refresh_startup_var(self) -> None:
        self._recolor_toggles()

    def _on_startup_toggle(self) -> None:
        p = self._startup_path()
        if not p:
            return
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
            return
        target = os.path.abspath(sys.argv[0] or __file__)
        exe = sys.executable.replace("python.exe", "pythonw.exe")
        if not os.path.exists(exe):
            exe = "pythonw.exe"
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            arg = f'"{exe}" "{target}"'
            line = f'CreateObject("WScript.Shell").Run "{arg.replace(chr(34), chr(34) * 2)}", 0, False\r\n'
            with open(p, "w", encoding="mbcs") as f:
                f.write(line)
        except OSError:
            pass

    # ------------------------------------------------------------ 关闭
    def show_front(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(60, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except Exception:
            pass

    def _on_close(self) -> None:
        pending = [it for it in self._items if not it.get("fired")]
        if pending:
            try:
                ok = messagebox.askyesno(APP_NAME, f"还有 {len(pending)} 条待提醒，退出后就不会提示了。\n确定退出吗？", parent=self)
            except Exception:
                ok = True
            if not ok:
                return
        self._stop_beep()
        for job in (self._flash_job, self._tick_job, self._err_job, self._clock_job):
            if job:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
        self._alive = False
        self._save()
        self.destroy()

# ==================================================================== 入口
_lock_sock: socket.socket | None = None


def acquire_single_instance() -> socket.socket | None:
    """拿到锁返回监听 socket；已有实例在跑则返回 None。"""
    global _lock_sock
    if not sys.platform.startswith("win"):
        _lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        return _lock_sock
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
    except OSError:
        s.close()
        return None
    _lock_sock = s
    return s


def nudge_running_instance() -> bool:
    """把已经开着的窗口叫到前台。"""
    try:
        with socket.create_connection(("127.0.0.1", LOCK_PORT), timeout=1.2) as c:
            c.sendall(b"show")
        return True
    except OSError:
        return False


def start_listener(app: "TodayTick", sock: socket.socket) -> None:
    def loop() -> None:
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            try:
                conn.recv(16)
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
            try:
                app.after(0, app.show_front)
            except Exception:
                return

    threading.Thread(target=loop, daemon=True).start()


def _selftest() -> int:
    base = datetime(2026, 11, 5, 14, 31)
    good = [
        ("14:35", datetime(2026, 11, 5, 14, 35)),
        ("9:05", datetime(2026, 11, 6, 9, 5)),      # 已过 -> 明天
        ("9点", datetime(2026, 11, 6, 9, 0)),
        ("9点30分", datetime(2026, 11, 6, 9, 30)),
        ("9点半", datetime(2026, 11, 6, 9, 30)),
        ("21点30分", datetime(2026, 11, 5, 21, 30)),
        ("1435", datetime(2026, 11, 5, 14, 35)),
        ("14:00", datetime(2026, 11, 6, 14, 0)),    # 已过 -> 明天
        ("明天 9:00", datetime(2026, 11, 6, 9, 0)),
        ("后天 8点", datetime(2026, 11, 7, 8, 0)),
        ("大后天 10:30", datetime(2026, 11, 8, 10, 30)),
        ("11-07 08:30", datetime(2026, 11, 7, 8, 30)),
        ("2026-12-01 07:15", datetime(2026, 12, 1, 7, 15)),
    ]
    bad = ["", "下午", "25:00", "13:70", "1-1"]
    fails = 0
    for raw, want in good:
        try:
            got = parse_target(raw, base)
        except ValueError:
            print(f"  parse FAIL  {raw!r} -> 不应该报错")
            fails += 1
            continue
        if got != want:
            print(f"  parse FAIL  {raw!r} -> {got} (期望 {want})")
            fails += 1
    for raw in bad:
        try:
            got = parse_target(raw, base)
            print(f"  parse FAIL  {raw!r} -> 竟然成功了 {got}")
            fails += 1
        except ValueError:
            pass
    rel = [("+5分", 5), ("+30分钟", 30), ("+1小时", 60), ("+1.5小时", 90)]
    now = datetime.now()
    for raw, minutes in rel:
        got = parse_target(raw, now)
        delta = (got - now).total_seconds() / 60
        if abs(delta - minutes) > 1:
            print(f"  rel FAIL    {raw!r} -> {delta:.1f} 分钟")
            fails += 1
    print("parse:", "PASS" if fails == 0 else f"FAIL ({fails})")

    app = TodayTick(selftest=True, data_path=os.path.join(os.environ.get("TEMP", "."), "todaytick_selftest.json"))
    app._items.clear()
    app._refresh_list()
    app.update()

    item = {"when": (datetime.now() - timedelta(minutes=1)).isoformat(timespec="minutes"), "text": "测试弹窗", "fired": True}
    app._items.append(item)
    app._build_popup(item)
    app.update()
    popup_ok = app._popup is not None
    print("popup:", "PASS" if popup_ok else "FAIL", {"fired": item["fired"], "popup": popup_ok})
    app._close_popup(item, snooze=True)
    app.update()
    snooze_ok = len(app._items) == 1 and app._items[0]["fired"] is False
    app._items[0]["when"] = (datetime.now() - timedelta(minutes=1)).isoformat(timespec="minutes")
    app._build_popup(app._items[0])
    app._close_popup(app._items[0])
    app.update()
    ack_ok = app._items == []
    print("snooze/ack:", "PASS" if (snooze_ok and ack_ok) else "FAIL", {"snooze": snooze_ok, "ack": ack_ok})

    # 布局：关键元素都在窗口内、底部开关与列表不重叠
    w, h = app.winfo_width(), app.winfo_height()
    layout_ok = True
    for tag in ("close", "addbtn"):
        bb = app.cv.bbox(tag) or (0, 0, 0, 0)
        if bb[2] > w or bb[3] > h:
            layout_ok = False
    list_bottom = app.list.winfo_y() + app.list.winfo_height()
    if list_bottom > app._foot_y - app.px(12):
        layout_ok = False
    print("layout:", "PASS" if layout_ok else "FAIL", {"win": (w, h), "list_bottom": list_bottom, "foot_y": app._foot_y})
    app._alive = False
    app.destroy()
    return 0 if (fails == 0 and popup_ok and snooze_ok and ack_ok and layout_ok) else 1


def main() -> int:
    global NO_GLASS
    NO_GLASS = "--no-glass" in sys.argv
    if "--selftest" in sys.argv:
        return _selftest()
    sock = acquire_single_instance()
    if sock is None:
        nudge_running_instance()
        return 0
    app = TodayTick()
    start_listener(app, sock)
    try:
        app.mainloop()
    finally:
        try:
            sock.close()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
