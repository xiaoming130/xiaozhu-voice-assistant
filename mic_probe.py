# -*- coding: utf-8 -*-
"""逐个探测录音设备，找出哪个能真采到声音。"""
import sounddevice as sd
import numpy as np

CANDIDATES = [1, 2, 36, 31, 35, 9, 3, 11, 22]

devices = sd.query_devices()
print(f"共 {len(devices)} 个设备\n")

results = []
for idx in CANDIDATES:
    try:
        d = devices[idx]
    except Exception:
        continue
    if d["max_input_channels"] < 1:
        continue

    name = d["name"]
    fs = int(d["default_samplerate"]) or 44100
    try:
        ch = min(1, d["max_input_channels"])
        rec = sd.rec(int(fs * 1.2), samplerate=fs, channels=ch,
                     device=idx, dtype="float32")
        sd.wait()
        rms = float(np.sqrt(np.mean(rec ** 2)))
        peak = float(np.max(np.abs(rec)))
        dbfs = 20 * np.log10(max(rms, 1e-9))
        verdict = "有信号" if rms > 1e-4 else "静音"
        results.append((idx, name, fs, rms, peak, dbfs, verdict))
        print(f"[{idx:2d}] {name[:38]:38s} fs={fs:6d} rms={rms:.6f} peak={peak:.6f} {dbfs:7.1f}dBFS  {verdict}")
    except Exception as e:
        print(f"[{idx:2d}] {name[:38]:38s} 打开失败: {str(e)[:60]}")

print()
alive = [r for r in results if r[3] > 1e-4]
if alive:
    print(f"结论: 有 {len(alive)} 个设备能采到信号")
    for a in alive:
        print(f"   -> [{a[0]}] {a[1]}")
else:
    print("结论: 所有设备均为静音。两种可能：")
    print("   1) 系统麦克风权限未开 / 设备被静音")
    print("   2) 当前进程运行在受限沙箱中，无权访问音频输入")
