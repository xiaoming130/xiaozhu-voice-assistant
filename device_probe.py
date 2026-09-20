# -*- coding: utf-8 -*-
"""device_probe.py —— 找出「耳机 (Realtek(R) Audio)」在两层 API 里的身份。

用途：
  1) sounddevice(MME/WASAPI) 层的输出设备清单 + 索引
  2) SAPI 层的可选输出目标清单
  3) 把目标名字在两层里分别做模糊匹配，看谁能命中

跑法（在项目目录下）:
  .venv\\Scripts\\python.exe device_probe.py
  .venv\\Scripts\\python.exe device_probe.py "耳机"
"""
import sys
import re

TARGET = sys.argv[1] if len(sys.argv) > 1 else "耳机"


def norm(s):
    """归一化：去掉括号内容差异、空格、大小写、全半角。"""
    s = (s or "").lower()
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"\s+", "", s)
    return s


def strip_paren(s):
    """去掉括号里的修饰（如 (Realtek(R) Audio)），便于宽松比对。"""
    return re.sub(r"[（(].*?[)）]", "", norm(s))


print("=" * 64)
print(f"目标关键字: {TARGET}")
print("=" * 64)

# ---------------------------------------------------------------- sounddevice
print()
print("## sounddevice 输出设备")
print("-" * 64)
sd_hits = []
try:
    import sounddevice as sd
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    for i, d in enumerate(devices):
        if d.get("max_output_channels", 0) <= 0:
            continue
        api = hostapis[d["hostapi"]]["name"] if d.get("hostapi") is not None else "?"
        name = d["name"]
        mark = ""
        if TARGET in name or TARGET in norm(name):
            mark = "  <== 命中"
            sd_hits.append(i)
        print(f"  [{i:>3}] {name}   (api={api}, out={d['max_output_channels']}, "
              f"fs={int(d.get('default_samplerate', 0))}){mark}")
    din, dout = sd.default.device
    print()
    print(f"  默认输出索引 = {dout}")
    if dout is not None and dout >= 0:
        print(f"  默认输出名称 = {devices[dout]['name']}")
except Exception as e:
    print("   sounddevice 失败:", e)

# ---------------------------------------------------------------- SAPI
print()
print("## SAPI 可选音频输出目标")
print("-" * 64)
sapi_hits = []
try:
    import comtypes.client
    voice = comtypes.client.CreateObject("SAPI.SpVoice", dynamic=True)
    outs = voice.GetAudioOutputs()
    n = outs.Count
    for i in range(n):
        try:
            desc = outs.Item(i).GetDescription()
        except Exception as e:
            desc = f"<读取失败: {e}>"
        mark = ""
        if TARGET in desc or TARGET in norm(desc) or strip_paren(TARGET) in strip_paren(desc):
            mark = "  <== 命中"
            sapi_hits.append(i)
        print(f"  [{i:>3}] {desc}{mark}")
    print()
    try:
        cur = voice.AudioOutput.GetDescription()
        print(f"  当前 SAPI 使用 = {cur}")
    except Exception as e:
        print("  读取当前失败:", e)
except Exception as e:
    print("   SAPI 失败:", e)

# ---------------------------------------------------------------- 结论
print()
print("=" * 64)
print("结论")
print("-" * 64)
print(f"  sounddevice 命中索引: {sd_hits if sd_hits else '无'}")
print(f"  SAPI 命中索引:        {sapi_hits if sapi_hits else '无'}")
if sd_hits:
    print()
    print(f"  => 可以按 sounddevice 索引 {sd_hits[0]} 定向播放。")
    print("     建议方案：TTS 渲染成 WAV，再用 sounddevice 指定该设备播放。")
else:
    print()
    print("  => sounddevice 没直接命中，可能需要放宽关键字（只匹配 Realtek）。")
