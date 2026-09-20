# -*- coding: utf-8 -*-
"""dressing_boot.py —— 打开 WorkBuddy 之后播一次穿衣建议，播完就退出。

为什么不用 headphone_watch.py 那条路：
    原设计是监听「耳机接入」这个事件。但萌哥的耳机是**一直插在电脑上**的，
    设备从开机起就常驻在场，「不在场 → 在场」这个边沿永远不会再发生，
    监听器等于永远不触发。所以改成由**外部时机**触发。

触发方式（config.json 的 dressing_boot.trigger）：
    "workbuddy"（默认）—— 等 **WorkBuddy.exe 进程出现**再播。
                           WorkBuddy 本身设了开机自启，所以实际效果就是
                           「WorkBuddy 一打开就播」，而且等的是它真的起来了，
                           比死等固定秒数稳。**等不到就不播了**（wb_required）。
    "boot"            —— 老行为：登录后静默 delay_sec 秒直接播。

好处：不需要任何常驻进程（也就不用被沙箱/杀软盯着），跑完即退，零内存占用。

执行顺序（每一步都有超时，不会把开机流程拖死）：
    0. 先静默等待 delay_sec —— 让桌面/音频服务起来
    1. 【trigger=workbuddy】等 WorkBuddy.exe 出现，最多 wb_timeout_sec
       —— 超时且 wb_required=true 就放弃本次（因为「它没开」）
    2. 等网络就绪（能连上 wttr.in），最多 network_timeout_sec
    3. 等目标音频输出设备出现，最多 device_timeout_sec（设备一直插着时秒过）
    4. 交给 dressing_brief.py 干正事：弹窗 + 取天气 + 语音播报 + 关窗
    5. 退出

谁来拉起它：启动文件夹里的 「小助-耳机穿衣播报.bat」
    （%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\）

单独跑（调试用）:
    python dressing_boot.py            # 完整流程（含等待）
    python dressing_boot.py --now      # 跳过所有等待，立刻跑
    python dressing_boot.py --dry      # 只打印会做什么，不实际执行
"""

import os
import sys
import json
import time
import socket
import subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

LOG_FILE = os.path.join(BASE_DIR, "dressing_boot.log")

DEFAULT_CFG = {
    "enabled": True,
    "trigger": "workbuddy",      # workbuddy=等 WorkBuddy 起来再播；boot=登录后直接播
    "wb_timeout_sec": 300,       # 最长等 WorkBuddy 多久（5 分钟）
    "wb_required": True,         # 等不到 WorkBuddy 时：True=本次不播，False=照样播
    "wb_image": "WorkBuddy.exe", # 要等的进程名
    "delay_sec": 5,              # 登录后先静默等这么久
    "network_timeout_sec": 120,  # 最长等网络多久
    "device_timeout_sec": 45,    # 最长等音频设备多久
    "probe_sec": 3,              # 等待时的探测间隔
}

CREATE_NO_WINDOW = 0x08000000

_DRY = "--dry" in sys.argv
_NOW = "--now" in sys.argv or _DRY


def log(msg):
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass
    print(msg, flush=True)


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    try:
        with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
            raw = json.load(f)
        cfg.update(raw.get("dressing_boot") or {})
        cfg["_full"] = raw
    except Exception as e:
        log(f"[cfg] 读取 config.json 失败，用默认值: {e}")
    return cfg


def net_ready(timeout=3):
    """能连上 wttr.in 就算网络就绪（只做 TCP 握手，不拉数据，快）。"""
    try:
        socket.create_connection(("wttr.in", 443), timeout=timeout).close()
        return True
    except OSError:
        return False


def wb_running(image="WorkBuddy.exe"):
    """WorkBuddy 进程是否在跑。

    Electron 会起一坨同名进程（主进程 + 各渲染进程 + GPU），命中任意一个即可。
    返回 True/False；查询本身失败时返回 None（当作「还不知道」，继续等）。
    """
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq " + image, "/NH"],
            capture_output=True, text=True,
            encoding="gbk", errors="replace",
            creationflags=CREATE_NO_WINDOW, timeout=15,
        )
        out = r.stdout or ""
        # 没有匹配时，tasklist 打的是「信息: 没有运行的任务匹配指定标准。」
        return image.lower() in out.lower()
    except Exception as e:
        log(f"[wb] 查询进程失败: {type(e).__name__} {e}")
        return None


def device_ready(must_include):
    """目标输出设备是否已在场（复用监听器那套判定，避免逻辑分叉）。"""
    try:
        import headphone_watch as hw
        names = hw.list_outputs()
        if not names:
            return None            # 枚举失败，不算就绪也不算失败
        return hw.match_target(names, must_include)
    except Exception as e:
        log(f"[dev] 枚举异常: {type(e).__name__} {e}")
        return None


def wait_until(fn, timeout_sec, probe_sec, label):
    """轮询等待 fn() 为真。返回 True=等到，False=超时。"""
    if _NOW:
        log(f"[wait] 跳过等待（--now）：{label}")
        return True
    t0 = time.time()
    last_note = 0
    while time.time() - t0 < timeout_sec:
        if fn():
            log(f"[wait] {label} 就绪，用时 {time.time() - t0:.0f}s")
            return True
        el = time.time() - t0
        if el - last_note >= 30:
            last_note = el
            log(f"[wait] 仍在等{label}… 已等 {el:.0f}s / 上限 {timeout_sec}s")
        time.sleep(probe_sec)
    log(f"[wait] 等{label}超时（{timeout_sec}s），不再等，继续往下走")
    return False


def run_brief(dry=False):
    """跑一次 dressing_brief.py（等到它结束）。"""
    pyw = os.path.join(BASE_DIR, ".venv", "Scripts", "pythonw.exe")
    py = pyw if os.path.exists(pyw) else sys.executable
    script = os.path.join(BASE_DIR, "dressing_brief.py")
    if dry:
        log(f"[brief] (dry) 将执行: {py} {script}")
        return 0
    r = subprocess.run([py, script], cwd=BASE_DIR,
                       stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=CREATE_NO_WINDOW, timeout=300)
    log(f"[brief] 结束，返回码 = {r.returncode}")
    return r.returncode


def main():
    t_start = time.time()
    cfg = load_cfg()
    full = cfg.get("_full") or {}
    must_include = (full.get("headphone_watch") or {}).get("must_include") \
        or ["耳机", "Realtek"]
    city = ((full.get("dressing_brief") or {}).get("city")) or "临沂"

    log("=" * 56)
    log(f"穿衣播报启动 (trigger={cfg.get('trigger', 'workbuddy')}, city={city}, "
        f"dry={_DRY}, skip_wait={_NOW})")

    if not cfg.get("enabled", True):
        log("[cfg] dressing_boot.enabled=false，本次不播，退出。")
        return 0

    # 1) 先静默等桌面起来
    delay = int(cfg.get("delay_sec", 5))
    if delay > 0 and not _NOW:
        log(f"[wait] 先等 {delay}s，让桌面/音频栈起来…")
        time.sleep(delay)

    # 2) 等 WorkBuddy 起来（默认触发条件）
    trigger = (cfg.get("trigger") or "workbuddy").strip().lower()
    if trigger == "workbuddy":
        image = cfg.get("wb_image") or "WorkBuddy.exe"
        timeout_wb = int(cfg.get("wb_timeout_sec", 300))
        got = wait_until(lambda: wb_running(image), timeout_wb,
                         int(cfg.get("probe_sec", 3)), image + " 启动")
        if not got and cfg.get("wb_required", True):
            log(f"[wb] 没等到 {image}（上限 {timeout_wb}s），"
                f"wb_required=true → 本次不播，退出。")
            return 0
        if got:
            log(f"[wb] {image} 已在跑，继续取天气。")
    else:
        log(f"[wb] trigger={trigger}，不等 WorkBuddy（老的开机即播行为）。")

    # 3) 等网络
    wait_until(lambda: net_ready(), int(cfg.get("network_timeout_sec", 120)),
               int(cfg.get("probe_sec", 3)), "网络")

    # 4) 等音频设备（设备常驻时这一跳几乎是瞬过）
    dev = device_ready(must_include)
    if dev:
        log(f"[dev] 目标输出设备在场: {dev}")
    else:
        wait_until(lambda: device_ready(must_include),
                   int(cfg.get("device_timeout_sec", 45)),
                   int(cfg.get("probe_sec", 3)), "目标音频设备")

    # 5) 干正事
    rc = run_brief(dry=_DRY)

    log(f"全部完成，总耗时 {time.time() - t_start:.1f}s")
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        try:
            log("[fatal] " + traceback.format_exc().replace("\n", " | "))
        except Exception:
            pass
        traceback.print_exc()
        sys.exit(1)
