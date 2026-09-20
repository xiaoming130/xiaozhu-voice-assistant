# -*- coding: utf-8 -*-
"""audio_check.py —— 三层音频输出测试，定位声音在哪一层断掉。

第 1 层  系统蜂鸣  winsound.Beep         （绕开 SAPI 和 sounddevice）
第 2 层  波形播放  sounddevice 正弦波     （走 PortAudio/WASAPI）
第 3 层  语音合成  SAPI 播报             （助手实际用的通道）
"""
import time

import numpy as np
import sounddevice as sd
import winsound

print("=" * 56)
print("第 1 层  系统蜂鸣 (winsound.Beep)")
print("=" * 56)
print("即将响三声高音，请留意...")
try:
    for f in (880, 1046, 1318):
        winsound.Beep(f, 400)
        time.sleep(0.12)
    print("  -> 已执行完毕")
except Exception as e:
    print("  -> 失败:", e)

print()
print("=" * 56)
print("第 2 层  波形播放 (sounddevice)")
print("=" * 56)
print("即将播放 1.2 秒 440Hz 音调...")
try:
    fs = 44100
    t = np.linspace(0, 1.2, int(fs * 1.2), False)
    tone = (0.35 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    _, dout = sd.default.device
    print("  输出设备:", sd.query_devices(dout)["name"])
    sd.play(tone, fs)
    sd.wait()
    print("  -> 已执行完毕")
except Exception as e:
    print("  -> 失败:", e)

print()
print("=" * 56)
print("第 3 层  语音合成 (SAPI，助手实际用的)")
print("=" * 56)
print("即将播报一句话...")
try:
    import pyttsx3
    eng = pyttsx3.init("sapi5")
    eng.setProperty("volume", 1.0)
    for v in eng.getProperty("voices"):
        if "chinese" in (v.name or "").lower() or "zh-cn" in (v.id or "").lower():
            eng.setProperty("voice", v.id)
            break
    eng.say("第三层测试，这是语音合成的声音。")
    eng.runAndWait()
    print("  -> 已执行完毕")
except Exception as e:
    print("  -> 失败:", e)

print()
print("=" * 56)
print("测试结束。请告诉小助：三层里哪几层听到了声音。")
print("=" * 56)
