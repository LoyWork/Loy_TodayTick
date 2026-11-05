"""量一次冷启动/暖启动到主窗出现的时间。"""
import ctypes
import subprocess
import sys
import time

u32 = ctypes.WinDLL("user32", use_last_error=True)
u32.FindWindowW.restype = ctypes.c_void_p
u32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]

EXE = r"D:\GitHub_Workspace\Loy_TodayTick\dist\TodayTick.exe"
TITLE = "TodayTick · 定时提醒"


def run(label):
    subprocess.run(["taskkill", "/F", "/IM", "TodayTick.exe"], capture_output=True)
    time.sleep(1.0)
    t0 = time.time()
    p = subprocess.Popen([EXE], cwd=r"D:\GitHub_Workspace\Loy_TodayTick\dist",
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    hwnd = 0
    while time.time() - t0 < 25:
        hwnd = u32.FindWindowW(None, TITLE)
        if hwnd:
            break
        time.sleep(0.1)
    dt = time.time() - t0
    print(f"{label}: 主窗出现 {'%.2fs' % dt if hwnd else '超时(25s)'}  hwnd={hwnd}  pid={p.pid}")
    if hwnd:
        # 再等到可见
        vis = u32.IsWindowVisible
        vis.argtypes = [ctypes.c_void_p]
        while time.time() - t0 < 25 and not vis(hwnd):
            time.sleep(0.1)
        print(f"{label}: 可见耗时 %.2fs" % (time.time() - t0))
    try:
        p.kill()
    except Exception:
        pass
    time.sleep(0.7)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "run")
