"""TodayTick (Tauri) 冒烟测试：python tools/smoke.py [exe 路径]"""

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x80000
WS_EX_TOPMOST = 0x8
SW_HIDE = 0

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "src-tauri", "target", "debug", "todaytick.exe")
MAIN_TITLE = "TodayTick · 定时提醒"
POPUP_TITLE = "提醒"

fails = []
notes = []


def check(name, ok, extra=""):
    line = f"{'PASS' if ok else 'FAIL'} {name}{(' ' + extra) if extra else ''}"
    print(line)
    notes.append(line)
    if not ok:
        fails.append(name)
    return ok


def find(title):
    return user32.FindWindowW(None, title)


def rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def wait_for(title, timeout, visible=False):
    end = time.time() + timeout
    while time.time() < end:
        hwnd = find(title)
        if hwnd and (not visible or user32.IsWindowVisible(hwnd)):
            return hwnd
        time.sleep(0.15)
    return 0


def wait_gone(title, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if not find(title):
            return True
        time.sleep(0.15)
    return False


def kill_all():
    subprocess.run(["taskkill", "/F", "/IM", "todaytick.exe"], capture_output=True)


def seed(data_dir):
    from datetime import datetime, timedelta

    due = (datetime.now() - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M")
    later = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    payload = {
        "version": "2.0",
        "sound": False,
        "items": [
            {"id": 1, "when": due, "text": "冒烟：该弹窗了", "fired": False},
            {"id": 2, "when": later, "text": "两小时后的会议", "fired": False},
        ],
        "next_id": 3,
    }
    path = os.path.join(data_dir, "reminders.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def main():
    if not os.path.exists(EXE):
        print(f"找不到 exe: {EXE}")
        return 2

    kill_all()
    time.sleep(0.4)
    data_dir = os.path.dirname(EXE)
    for name in ("reminders.json", "reminders.json.tmp"):
        p = os.path.join(data_dir, name)
        if os.path.exists(p):
            os.remove(p)
    data_path = seed(data_dir)

    env = dict(os.environ)
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=9333"
    err_path = os.path.join(data_dir, ".smoke_stderr.log")
    err_file = open(err_path, "wb")
    proc = subprocess.Popen(
        [EXE],
        env=env,
        cwd=data_dir,
        stdout=subprocess.DEVNULL,
        stderr=err_file,
    )

    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    print(f"屏幕 {sw}x{sh}")

    main_hwnd = wait_for(MAIN_TITLE, 25, visible=True)
    if not check("主窗出现且可见", bool(main_hwnd)):
        proc.kill()
        return 1

    time.sleep(1.0)  # 等前端首帧 resize/定位完成
    x, y, w, h = rect(main_hwnd)
    style = user32.GetWindowLongW(main_hwnd, -16) & 0xFFFFFFFF
    exstyle = user32.GetWindowLongW(main_hwnd, -20) & 0xFFFFFFFF
    check("主窗无标题栏", (style & 0x00C00000) == 0, f"style={hex(style)}")
    check("主窗有任务栏按钮", (exstyle & 0x00040000) != 0, f"exstyle={hex(exstyle)}")
    check("主窗宽度 384", w == 384, f"{w}")
    check("高度自适应范围", 280 <= h <= 640, f"h={h}")
    expect_x = sw - 384 - 26
    expect_bottom = sh - 64
    check(
        "贴右下角",
        abs(x - expect_x) <= 2 and abs((y + h) - expect_bottom) <= 3,
        f"rect=({x},{y},{w},{h})",
    )

    popup_hwnd = wait_for(POPUP_TITLE, 20, visible=True)
    if check("到期弹窗出现", bool(popup_hwnd)):
        px, py, pw, ph = rect(popup_hwnd)
        check("弹窗宽度 320", pw == 320, f"{pw}")
        check("弹窗置顶", bool(user32.GetWindowLongW(popup_hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST))
        work = wintypes.RECT()
        work_ok = user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)
        check(
            "弹窗位于工作区右下角，避开任务栏",
            bool(work_ok)
            and abs((px + pw) - (work.right - 16)) <= 3
            and abs((py + ph) - (work.bottom - 16)) <= 3,
            f"rect=({px},{py},{pw},{ph}) work=({work.left},{work.top},{work.right},{work.bottom})",
        )

    time.sleep(0.6)
    with open(data_path, encoding="utf-8") as fh:
        data = json.load(fh)
    fired = {it["id"]: it["fired"] for it in data["items"]}
    check("到期项标记 fired", fired.get(1) is True, str(fired))
    check("未到期项未触发", fired.get(2) is False, str(fired))

    # 第二实例：应瞬间退出并把主窗抬起来
    t0 = time.time()
    second = subprocess.run([EXE], capture_output=True, timeout=20)
    dt = time.time() - t0
    check("第二实例秒退", second.returncode == 0 and dt < 8, f"rc={second.returncode} {dt:.1f}s")
    check("仍只有一个主窗", find(MAIN_TITLE) != 0 and proc.poll() is None)

    # 主窗尺寸自适应检查（空态/多条对比稍后由调用方另行验证）
    notes.append(f"main_rect={rect(main_hwnd)}")

    err_file.close()
    try:
        with open(err_path, encoding="utf-8", errors="replace") as fh:
            stderr_text = fh.read()
    except OSError:
        stderr_text = ""
    check("托盘创建无报错", "托盘创建失败" not in stderr_text, stderr_text.strip()[:120])
    check("启动无 panic", "panicked" not in stderr_text, stderr_text.strip()[:120])

    proc.kill()
    proc.wait(timeout=10)
    check("进程退出干净", wait_gone(MAIN_TITLE, 6))

    print("\n".join(["", "SMOKE PASS" if not fails else "SMOKE FAIL: " + ", ".join(fails)]))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
