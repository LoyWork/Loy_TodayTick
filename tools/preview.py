"""生成预览图：python tools/preview.py

流程：清场 → 写入示例提醒（一条已到期用于弹窗）→ 带 CDP 端口启动 exe
→ 等主窗/弹窗出现 → 调 node tools/shot.mjs 抓图 → 关闭进程。
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    ROOT, "src-tauri", "target", "debug", "todaytick.exe"
)


def seed(path):
    now = datetime.now()
    due = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
    items = [
        {"id": 1, "when": due, "text": "喝水，站起来走两分钟", "fired": False},
        {"id": 2, "when": (now + timedelta(minutes=25)).strftime("%Y-%m-%dT%H:%M"), "text": "把周报发出去", "fired": False},
        {"id": 3, "when": (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"), "text": "三点半的评审会 · 记得带充电器", "fired": False},
        {"id": 4, "when": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"), "text": "明天早上的体检，空腹", "fired": False},
    ]
    payload = {"version": "2.1", "items": items, "next_id": 5}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def main():
    subprocess.run(["taskkill", "/F", "/IM", "todaytick.exe"], capture_output=True)
    time.sleep(0.5)

    data_dir = os.path.dirname(EXE)
    seed(os.path.join(data_dir, "reminders.json"))

    env = dict(os.environ)
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=9333"
    proc = subprocess.Popen(
        [EXE], env=env, cwd=data_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    deadline = time.time() + 30
    port_ok = False
    while time.time() < deadline:
        try:
            import urllib.request

            with urllib.request.urlopen("http://127.0.0.1:9333/json/list", timeout=2) as resp:
                targets = json.load(resp)
            pages = [t for t in targets if t.get("type") == "page"]
            if len(pages) >= 2:
                port_ok = True
                break
        except Exception:
            pass
        time.sleep(0.5)

    if not port_ok:
        print("CDP 页面不足（主窗/弹窗未就绪），继续尝试抓图")

    time.sleep(1.2)
    lay = subprocess.run(
        ["node", os.path.join(ROOT, "tools", "layout.mjs")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    tail = [ln for ln in lay.stdout.strip().splitlines() if ln.startswith(("PASS", "FAIL"))]
    print("\n".join(tail[-6:]) if tail else lay.stdout.strip()[:400])
    shot = subprocess.run(
        ["node", os.path.join(ROOT, "tools", "shot.mjs"), os.path.join(ROOT, "docs")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(shot.stdout.strip())
    if shot.returncode != 0:
        print(shot.stderr.strip())

    proc.kill()
    proc.wait(timeout=10)
    return 0 if shot.returncode == 0 and lay.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
