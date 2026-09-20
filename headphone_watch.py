# -*- coding: utf-8 -*-
"""headphone_watch.py —— 常驻监听：一旦「耳机 (Realtek(R) Audio)」这个输出设备
出现在系统里（插上耳机 / 开机时已插着），就自动跑一次 dressing_brief.py：
弹窗 + 语音播报今天温度和该穿什么。

为什么用 SAPI 枚举来探测设备：
    sounddevice(PortAudio) 的设备表是进程启动时快照的，插拔耳机不刷新，
    得 _terminate/_initialize 才能重读，重且重；
    而 SAPI 的 GetAudioOutputs() 每次调用都是【实时重枚举】，拿到的正是
    播报要用的那一层设备，零额外依赖、口径还一致。所以用它。

为什么关键词要「全部命中」：
    机器上可能同时存在多副耳机，例如
        [1] 耳机 (HG9086WS)            <- 蓝牙耳机，不是目标
        [4] 耳机 (Realtek(R) Audio)    <- 目标
        [0] 扬声器 (Realtek(R) Audio)  <- 3.5mm 外放口，不是目标
    只认『耳机』会误命中蓝牙耳机，只认『Realtek』会误命中扬声器，
    所以必须 must_include = ["耳机", "Realtek"] 全部命中才算数。

跑法:
    python headphone_watch.py            # 常驻监听（开机自启用的就是这个）
    python headphone_watch.py --once     # 只查一次，打印结果就退出（调试用）
    python headphone_watch.py --status   # 列全部输出设备 + 判定结论（调试用）
    python headphone_watch.py --force    # 无视边沿，立刻触发一次播报（调试用）

依赖：comtypes（已在 .venv 内）
"""

import os
import sys
import json
import time
import signal
import ctypes
import subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "dressing_watch.log")
HEARTBEAT = os.path.join(BASE_DIR, "dressing_watch.heartbeat")
PID_FILE = os.path.join(BASE_DIR, "dressing_watch.pid")

DEFAULT_CFG = {
    "enabled": True,
    "must_include": ["耳机", "Realtek"],
    "poll_sec": 5,
    "cooldown_sec": 120,
    "fire_on_start": True,
}

CREATE_DETACHED = 0x00000008
CREATE_NEW_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

_stop = False

# 单实例锁：开机自启和手动启动可能撞车，用命名互斥体挡住第二个实例。
# 句柄要一直持有（挂到模块级），进程退出时系统自动释放。
_MUTEX_NAME = "Global\\xiaozhu_headphone_watch_v1"
_mutex_handle = None
ERROR_ALREADY_EXISTS = 183


def acquire_single_instance():
    """拿到锁返回 True；已有实例在跑返回 False。"""
    global _mutex_handle
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = ctypes.c_void_p
        _mutex_handle = k32.CreateMutexW(None, False, _MUTEX_NAME)
        if not _mutex_handle:
            return True            # 拿不到锁对象就不挡自己，正常跑
        if k32.GetLastError() == ERROR_ALREADY_EXISTS:
            return False
        return True
    except Exception:
        return True


# ----------------------------------------------------------------- 日志

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        # 简单限长，别让日志无限涨
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1_000_000:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-500:]
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.writelines(tail)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


def touch_heartbeat():
    try:
        with open(HEARTBEAT, "w", encoding="utf-8") as f:
            f.write(str(int(time.time())))
    except Exception:
        pass


# ----------------------------------------------------------------- 配置

def load_cfgs():
    cfg = {}
    try:
        with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        log(f"[cfg] 读取 config.json 失败，用默认值: {e}")
    w = dict(DEFAULT_CFG)
    w.update(cfg.get("headphone_watch") or {})
    return cfg, w


# ----------------------------------------------------------------- 设备探测

def list_outputs():
    """实时枚举 SAPI 层的音频输出设备名。失败返回 None。"""
    try:
        import comtypes.client
        v = comtypes.client.CreateObject("SAPI.SpVoice", dynamic=True)
        outs = v.GetAudioOutputs()
        names = []
        for i in range(outs.Count):
            try:
                names.append(outs.Item(i).GetDescription())
            except Exception:
                continue
        return names
    except Exception as e:
        log(f"[dev] 枚举失败: {type(e).__name__} {e}")
        return None


def match_target(names, must_include):
    """must_include 里的关键词必须【全部命中】才返回该设备名，否则 None。"""
    kws = [(k or "").lower() for k in must_include if k]
    if not kws:
        return None
    for n in names:
        low = (n or "").lower()
        if all(k in low for k in kws):
            return n
    return None


# ----------------------------------------------------------------- 触发

def fire(reason):
    """脱管跑一次 dressing_brief.py。"""
    pyw = os.path.join(BASE_DIR, ".venv", "Scripts", "pythonw.exe")
    py = pyw if os.path.exists(pyw) else sys.executable
    script = os.path.join(BASE_DIR, "dressing_brief.py")
    try:
        p = subprocess.Popen(
            [py, script], cwd=BASE_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_DETACHED | CREATE_NEW_GROUP | CREATE_NO_WINDOW,
            close_fds=True,
        )
        log(f"[fire] 触发穿衣播报（{reason}），pid={p.pid}")
        return True
    except Exception as e:
        log(f"[fire] 触发失败: {type(e).__name__} {e}")
        return False


# ----------------------------------------------------------------- 主循环

def _on_signal(signum, frame):
    global _stop
    _stop = True
    log(f"[sig] 收到信号 {signum}，准备退出")


def cmd_status(must_include):
    names = list_outputs()
    if names is None:
        print("枚举失败")
        return 2
    print(f"SAPI 输出设备共 {len(names)} 个：")
    for i, n in enumerate(names):
        low = n.lower()
        hit = all((k or "").lower() in low for k in must_include if k)
        print(f"  [{i}] {n}" + ("   <== 目标耳机命中" if hit else ""))
    t = match_target(names, must_include)
    print()
    print(f"判定关键词: {must_include}")
    print(f"结论: {'在场 -> ' + t if t else '不在场'}")
    return 0


def cmd_once(cfg, w):
    """查一次，如果设备在场就照样走一遍完整逻辑（含边沿）。"""
    names = list_outputs()
    t = match_target(names or [], w["must_include"])
    print("目标耳机:", t or "不在场")
    return 0


def main():
    args = sys.argv[1:]
    cfg, w = load_cfgs()

    if "--status" in args:
        return cmd_status(w["must_include"])

    if "--once" in args:
        return cmd_once(cfg, w)

    if not w.get("enabled", True):
        log("[init] config 里 headphone_watch.enabled=false，监听未启动。")
        return 0

    if not acquire_single_instance():
        log("[init] 已有监听实例在运行，本次启动自动退出（单实例保护）。")
        return 0

    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    poll = max(1, int(w.get("poll_sec", 5)))
    cooldown = max(0, int(w.get("cooldown_sec", 120)))
    fire_on_start = bool(w.get("fire_on_start", True))

    log("=" * 56)
    log(f"[init] 耳机监听启动  关键词={w['must_include']}  "
        f"轮询={poll}s 冷却={cooldown}s 启动补触发={fire_on_start}")
    log(f"[init] 目标动作 = 启动「穿衣建议.exe」+ 语音播报（城市见 config.dressing_brief.city）")

    prev = None          # 上一轮是否在场
    last_fire = 0.0      # 上次触发时刻
    first_poll = True
    fail_streak = 0

    if "--force" in args:
        fire("手动 --force")
        last_fire = time.time()

    while not _stop:
        touch_heartbeat()
        names = list_outputs()

        if names is None:
            fail_streak += 1
            if fail_streak in (1, 10, 60) or fail_streak % 300 == 0:
                log(f"[dev] 连续枚举失败 {fail_streak} 次，继续重试")
            time.sleep(poll)
            continue
        fail_streak = 0

        target = match_target(names, w["must_include"])
        present = target is not None

        if prev is None:
            log(f"[dev] 首次检测: {'在场 -> ' + target if present else '不在场'}（当前共 {len(names)} 个输出设备）")

        # 边沿：不在场 -> 在场
        arrived = (prev is False and present) or (prev is None and present and fire_on_start)

        if arrived:
            if time.time() - last_fire >= cooldown:
                fire(f"检测到耳机接入: {target}")
                last_fire = time.time()
            else:
                log(f"[dev] 检测到耳机接入，但仍在冷却期（{cooldown}s），跳过")

        prev = present
        first_poll = False

        # 分片 sleep，保证信号能被及时响应
        slept = 0.0
        while slept < poll and not _stop:
            time.sleep(0.25)
            slept += 0.25

    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass
    log("[exit] 耳机监听已停止")
    return 0


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
