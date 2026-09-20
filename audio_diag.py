# -*- coding: utf-8 -*-
"""audio_diag.py —— 诊断语音被送到了哪个输出设备。

SAPI 有自己的 AudioOutput 列表，未必等于系统默认播放设备。
如果两者不一致，就会「日志显示播报了，但人听不到」。
"""
import comtypes.client
import sounddevice as sd

print("=" * 56)
print("系统默认播放设备")
print("=" * 56)
try:
    din, dout = sd.default.device
    if dout is not None and dout >= 0:
        print("  ", sd.query_devices(dout)["name"])
    else:
        print("   未设置")
except Exception as e:
    print("   读取失败:", e)

print()
print("=" * 56)
print("SAPI 音频输出目标")
print("=" * 56)
cur_desc = None
try:
    voice = comtypes.client.CreateObject("SAPI.SpVoice", dynamic=True)
    outs = voice.GetAudioOutputs()
    n = outs.Count
    print(f"   共 {n} 个可选")
    for i in range(n):
        try:
            desc = outs.Item(i).GetDescription()
        except Exception as e:
            desc = f"<读取失败: {e}>"
        print(f"   [{i}] {desc}")

    print()
    print("=" * 56)
    print("当前实际使用")
    print("=" * 56)
    try:
        cur = voice.AudioOutput
        cur_desc = cur.GetDescription()
        print("  ", cur_desc)
    except Exception as e:
        print("   读取失败:", e)
except Exception as e:
    print("   SAPI 访问失败:", e)
    print("   （如果这里是 COM 报错，说明沙箱禁了 COM，需要用别的方式）")
