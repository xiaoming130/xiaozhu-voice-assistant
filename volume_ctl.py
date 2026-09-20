# -*- coding: utf-8 -*-
"""volume_ctl.py —— 查看/设置「播报输出设备」在 Windows 里的总音量。

⚠️ 先分清两层音量，别调错了：

    软件层（config.json）          系统层（本脚本管的）
    ├ volume: 1.0        TTS 音量   └ 设备音量滑块（声音合成器里那一根）
    └ chime_volume: 0.9  铃声增益       ← 这才是「总闸」

    config.json 里的 1.0 已经是 SAPI 的上限，再怎么调也到顶；
    真正决定「响不响」的是 Windows 里那只设备的音量滑块。
    实测坑：耳机设备被压在 **12%**，于是铃声和语音全都小得可怜。

用法:
    python volume_ctl.py                  看目标设备（config 的 output_device）音量
    python volume_ctl.py --all            列出所有输出设备音量
    python volume_ctl.py 70               把目标设备音量设成 70%
    python volume_ctl.py 70 "扬声器"       指定别的设备（名字模糊匹配）
    python volume_ctl.py --mute           静音
    python volume_ctl.py --unmute         取消静音
"""
import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import tts_core                                            # noqa: E402
from tts_core import _score, norm                          # noqa: E402

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")


def target_name(cli=None):
    if cli:
        return cli
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return (json.load(f).get("output_device") or "").strip()
    except Exception:
        return ""


def all_devices():
    """返回 [(友好名, IAudioEndpointVolume 接口), ...]，读不到的跳过。

    GetAllDevices() 会列出很多「幽灵」端点（拔掉的/虚拟的），
    对它们取属性会抛 COM 错误，所以每一项都单独 try。
    """
    from pycaw.pycaw import AudioUtilities

    out = []
    for d in AudioUtilities.GetAllDevices():
        try:
            ev = getattr(d, "EndpointVolume", None)
            if ev is None:
                continue
        except Exception:
            continue
        try:
            name = d.FriendlyName
            ev.GetMasterVolumeLevelScalar()      # 探一下，幽灵端点会在这里炸
        except Exception:
            continue
        out.append((name, ev))
    return out


def find(name):
    """按名字模糊匹配（复用 tts_core 的打分规则，和播报同一套口径）。"""
    want = norm(name)
    best = None  # (score, friendly, ev)
    for friendly, ev in all_devices():
        sc = _score(want, norm(friendly))
        if sc > (best[0] if best else 0):
            best = (sc, friendly, ev)
    return best


def fmt(ev):
    try:
        vol = ev.GetMasterVolumeLevelScalar()
        mute = bool(ev.GetMute())
    except Exception as e:
        return f"读取失败: {e}"
    return f"{vol * 100:5.1f}%  {'[静音]' if mute else ''}"


def main():
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("value", nargs="?", type=float,
                   help="要设置的音量百分比，0-100")
    p.add_argument("device", nargs="?", default=None,
                   help="设备名关键字（默认用 config.json 的 output_device）")
    p.add_argument("--all", action="store_true", help="列出所有输出设备")
    p.add_argument("--mute", action="store_true")
    p.add_argument("--unmute", action="store_true")
    args = p.parse_args()

    if args.all:
        for friendly, ev in sorted(all_devices(), key=lambda x: x[0]):
            print(f"  {fmt(ev)}  {friendly}")
        return 0

    name = target_name(args.device)
    if not name:
        print("没有指定设备，且 config.json 里 output_device 为空。用 --all 看看有哪些。")
        return 1

    best = find(name)
    if best is None:
        print(f"没找到匹配『{name}』的输出设备。用 --all 看看有哪些。")
        return 1

    _, friendly, ev = best
    if args.value is None and not args.mute and not args.unmute:
        print(f"目标设备: {friendly}")
        print(f"当前音量: {fmt(ev)}")
        return 0

    if args.mute:
        ev.SetMute(True, None)
    if args.unmute:
        ev.SetMute(False, None)
    if args.value is not None:
        v = max(0.0, min(100.0, args.value)) / 100.0
        ev.SetMasterVolumeLevelScalar(v, None)

    print(f"目标设备: {friendly}")
    print(f"现在音量: {fmt(ev)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
