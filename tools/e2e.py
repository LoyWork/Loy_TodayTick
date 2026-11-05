"""端到端检查入口：python tools/e2e.py [exe]

阶段 A：干净数据启动 → 跑 tools/uicheck.mjs（主窗交互）
阶段 B：播种两条已到期 → 重启 → 跑 tools/popupcheck.mjs（弹窗交互）
"""

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    ROOT, "src-tauri", "target", "debug", "todaytick.exe"
)
MAIN_TITLE = "TodayTick · 定时提醒"

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.IsWindowVisible.argtypes = [wintypes.HWND]


def kill_app():
    subprocess.run(["taskkill", "/F", "/IM", "todaytick.exe"], capture_output=True)
    time.sleep(0.6)


def clean_data(data_dir):
    for name in ("reminders.json", "reminders.json.tmp"):
        path = os.path.join(data_dir, name)
        if os.path.exists(path):
            os.remove(path)


def seed_due(data_dir):
    now = datetime.now()
    p = "%Y-%m-%dT%H:%M"
    payload = {
        "version": "2.0",
        "sound": False,
        "items": [
            {"id": 1, "when": (now - timedelta(minutes=3)).strftime(p), "text": "第一条：喝水，站起来走两步", "fired": False},
            {"id": 2, "when": (now - timedelta(minutes=2)).strftime(p), "text": "第二条：三点半的评审会", "fired": False},
            {"id": 3, "when": (now + timedelta(hours=2)).strftime(p), "text": "两小时后的事", "fired": False},
        ],
        "next_id": 4,
    }
    with open(os.path.join(data_dir, "reminders.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def launch(data_dir):
    env = dict(os.environ)
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=9333"
    proc = subprocess.Popen(
        [EXE], env=env, cwd=data_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    end = time.time() + 25
    while time.time() < end:
        hwnd = user32.FindWindowW(None, MAIN_TITLE)
        if hwnd and user32.IsWindowVisible(hwnd):
            time.sleep(1.0)
            return proc
        time.sleep(0.2)
    proc.kill()
    return None


def run_node(script, timeout=180):
    res = subprocess.run(
        ["node", os.path.join(ROOT, "tools", script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    print(res.stdout.strip())
    if res.returncode != 0 and res.stderr.strip():
        print(res.stderr.strip())
    return res.returncode


def main():
    if not os.path.exists(EXE):
        print(f"找不到 exe: {EXE}")
        return 2
    data_dir = os.path.dirname(EXE)

    # 阶段 A：主窗交互
    kill_app()
    clean_data(data_dir)
    proc = launch(data_dir)
    if not proc:
        print("阶段 A：主窗没起来")
        return 1
    code_a = run_node("uicheck.mjs")

    # 阶段 A2：关掉窗口 → 真的隐藏 → 再运行一次能叫回来（等同托盘/任务栏恢复路径）
    code_h = run_node("hidecheck.mjs")
    time.sleep(1.0)
    hwnd = user32.FindWindowW(None, MAIN_TITLE)
    hidden_ok = bool(hwnd) and not user32.IsWindowVisible(hwnd)
    print(("PASS" if hidden_ok else "FAIL") + " 关掉窗口后主窗隐藏")
    subprocess.run([EXE], capture_output=True, timeout=20)
    time.sleep(1.6)
    hwnd2 = user32.FindWindowW(None, MAIN_TITLE)
    shown_ok = bool(hwnd2) and bool(user32.IsWindowVisible(hwnd2))
    print(("PASS" if shown_ok else "FAIL") + " 再次运行可唤回窗口")
    if not hidden_ok or not shown_ok:
        code_h = 1

    proc.kill()
    proc.wait(timeout=10)
    kill_app()

    # 阶段 B：弹窗交互
    clean_data(data_dir)
    seed_due(data_dir)
    proc = launch(data_dir)
    if not proc:
        print("阶段 B：主窗没起来")
        return 1
    code_b = run_node("popupcheck.mjs")
    proc.kill()
    proc.wait(timeout=10)
    kill_app()
    clean_data(data_dir)

    print(f"\n阶段 A rc={code_a}  隐藏/唤回 rc={code_h}  阶段 B rc={code_b}")
    return 0 if code_a == 0 and code_h == 0 and code_b == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
