# -*- coding: utf-8 -*-
"""chime.py —— 从指定输出设备响一声提示音。

用法:
    python chime.py                      默认音色 + config.json 里的输出设备
    python chime.py done                 指定音色
    python chime.py alert "耳机"          指定音色 + 指定设备
    python chime.py --list               列出可选音色和输出设备

音色: done(默认) / soft / alert / error

为什么不用 winsound.Beep：它只会跟着系统默认设备跑，而且音色不可控。
这里用 numpy 合成波形、sounddevice 指定设备播放，和播报走同一只耳机。
"""
import argparse
import json
import os
import re
import sys

import numpy as np

from chime_kinds import DEFAULT as DEFAULT_KIND
from chime_kinds import KINDS, MEANING

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
LOG_FILE = os.path.join(BASE_DIR, "tts.log")

FS = 44100

# 每个音色 = [(频率Hz, 时长秒), ...]，依次播放
CHIMES = {
    # 任务完成：上行三音，明亮不刺耳
    "done": [(1046.5, 0.11), (1318.5, 0.11), (1568.0, 0.32)],
    # 提问：上行两音（疑问语气上扬），和 done 的三音区分开
    "ask": [(880.0, 0.13), (1174.7, 0.30)],
    # 轻柔单音：只要一个存在感
    "soft": [(1174.7, 0.24)],
    # 提醒：两声同音，像「叮咚」
    "alert": [(880.0, 0.13), (880.0, 0.26)],
    # 出错：下行两音
    "error": [(740.0, 0.15), (587.3, 0.30)],
}

# 清单与波形定义必须一一对应 —— 加音色时漏改一处会很难查，这里直接卡住
assert set(CHIMES) == set(KINDS), (
    "chime.py 的 CHIMES 与 chime_kinds.KINDS 不一致，差集: "
    f"{sorted(set(CHIMES) ^ set(KINDS))}"
)


# ---------------------------------------------------------------- 设备匹配

def norm(s):
    s = (s or "").lower()
    s = s.replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", "", s)


def bare(s):
    return re.sub(r"\(.*", "", norm(s))


def _score(want, have):
    if not want or not have:
        return 0
    if want == have:
        return 3
    wb, hb = bare(want), bare(have)
    if wb and wb == hb:
        return 2
    if want in have:
        return 1
    return 0


def resolve_device(name, verbose=False):
    """按名字找输出设备索引。找不到返回 None（= 系统默认）。

    同名设备会在 MME / DirectSound / WASAPI / WDM-KS 里重复出现，
    优先选 MME —— 兼容性最好，且和 config.json 里那个名字对得上。
    """
    import sounddevice as sd

    if not (name or "").strip():
        return None

    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    want = norm(name)

    best = None  # (score, prefer_mme, index, devname)
    for i, d in enumerate(devices):
        if d.get("max_output_channels", 0) <= 0:
            continue
        api = hostapis[d["hostapi"]]["name"]
        if "WDM-KS" in api:          # WDM-KS 独占性太强，跳过
            continue
        sc = _score(want, norm(d["name"]))
        if sc == 0:
            continue
        prefer = 1 if api == "MME" else 0
        key = (sc, prefer)
        if best is None or key > best[0]:
            best = (key, i, d["name"], api)

    if best is None:
        return None
    _, idx, devname, api = best
    if verbose:
        print(f"[device] [{idx}] {devname}  ({api})")
    return idx


def list_devices():
    import sounddevice as sd

    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    for i, d in enumerate(devices):
        if d.get("max_output_channels", 0) <= 0:
            continue
        api = hostapis[d["hostapi"]]["name"]
        print(f"  [{i:>3}] {d['name']}   ({api})")


# ---------------------------------------------------------------- 合成

def _tone(freq, dur, amp=0.7, decay=7.0):
    """一个带指数衰减包络的正弦音，首尾加淡入淡出防咔哒。

    amp 原来是 0.35 —— 峰值只有满量程的 1/3，听感偏小（萌哥反馈过）。
    提到 0.7 后响度约 +6dB，仍留足余量不削波（synth 里还有 0.9 的兜底）。
    """
    n = max(int(FS * dur), 1)
    t = np.arange(n) / FS
    wave = np.sin(2 * np.pi * freq * t)
    env = np.exp(-decay * t)
    n_in = max(int(FS * 0.004), 1)
    env[:n_in] *= np.linspace(0.0, 1.0, n_in)
    return (amp * wave * env).astype(np.float32)


def synth(kind=DEFAULT_KIND, gap=0.02, volume=1.0):
    """把音色合成成一段 float32 波形。"""
    notes = CHIMES.get(kind) or CHIMES[DEFAULT_KIND]
    parts = []
    for freq, dur in notes:
        parts.append(_tone(freq, dur))
        if gap > 0:
            parts.append(np.zeros(int(FS * gap), dtype=np.float32))
    audio = np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32)

    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 0.9:                      # 防削波
        audio = audio * (0.9 / peak)
    return (audio * float(volume)).astype(np.float32)


# ---------------------------------------------------------------- 播放

def log_line(msg):
    try:
        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def default_device_name():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return (json.load(f).get("output_device") or "").strip()
    except Exception:
        return ""


def play(kind=DEFAULT_KIND, device=None, volume=1.0, verbose=False):
    """响一声。device 为空则用 config.json 的 output_device，再不行用系统默认。"""
    import sounddevice as sd

    name = device if device is not None else default_device_name()
    idx = resolve_device(name, verbose=verbose)

    audio = synth(kind, volume=volume)
    if verbose:
        print(f"[chime] {kind}  {len(audio) / FS:.2f}s  vol={volume}")

    if idx is None and name:
        log_line(f"[chime] 未匹配到『{name}』，已退回系统默认设备")
    log_line(f"[chime] {kind} -> {name or '系统默认'}")

    sd.play(audio, FS, device=idx)
    sd.wait()
    return True


def main():
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("kind", nargs="?", default=DEFAULT_KIND,
                   help=f"音色: {' / '.join(CHIMES)}")
    p.add_argument("device", nargs="?", default=None, help="输出设备关键字")
    p.add_argument("--volume", type=float, default=1.0)
    p.add_argument("--list", action="store_true", help="列出音色和输出设备")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    if args.list:
        print("音色:")
        for k, notes in CHIMES.items():
            total = sum(d for _, d in notes) + 0.02 * (len(notes) - 1)
            print(f"  {k:<6} {total:.2f}s  {len(notes)} 音")
        print()
        print("输出设备:")
        list_devices()
        print()
        print(f"config.json 里的 output_device = {default_device_name()!r}")
        return 0

    if args.kind not in CHIMES:
        print(f"未知音色 {args.kind!r}，可选: {' / '.join(CHIMES)}")
        return 1

    play(args.kind, args.device, args.volume, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
