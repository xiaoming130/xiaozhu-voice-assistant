# -*- coding: utf-8 -*-
"""
stt_test.py —— 语音识别闭环测试
出声提示 -> 录音 -> 本地识别 -> 播报识别结果
"""
import os
import sys
import numpy as np

import sounddevice as sd
import pyttsx3
from faster_whisper import WhisperModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "models", "faster-whisper-base")

MIC_DEVICE = 2          # 麦克风阵列 (Realtek(R) Audio)
REC_FS = 44100          # 按设备原生采样率录，再重采样
TARGET_FS = 16000       # whisper 要求 16k
REC_SECONDS = 6


def speak(text, rate=185):
    e = pyttsx3.init("sapi5")
    e.setProperty("rate", rate)
    for v in e.getProperty("voices"):
        if "chinese" in (v.name or "").lower() or "zh-cn" in (v.id or "").lower():
            e.setProperty("voice", v.id)
            break
    e.say(text)
    e.runAndWait()


def resample(audio, src_fs, dst_fs):
    if src_fs == dst_fs:
        return audio
    n = int(len(audio) * dst_fs / src_fs)
    return np.interp(np.linspace(0, len(audio) - 1, n),
                     np.arange(len(audio)), audio).astype(np.float32)


def main():
    print("=" * 52)
    print("步骤 1/3  出声提示")
    speak("请说一句话，我来识别。")
    print("   已提示")

    print(f"步骤 2/3  录音 {REC_SECONDS} 秒（现在请说话）...")
    rec = sd.rec(int(REC_FS * REC_SECONDS), samplerate=REC_FS,
                 channels=1, device=MIC_DEVICE, dtype="float32")
    sd.wait()
    audio = rec.flatten()
    rms = float(np.sqrt(np.mean(audio ** 2)))
    print(f"   采集完成  电平 {20 * np.log10(max(rms, 1e-9)):.1f} dBFS")
    if rms < 1e-4:
        print("   警告: 录制几乎无声，识别结果不会准")

    audio = resample(audio, REC_FS, TARGET_FS)
    peak = float(np.max(np.abs(audio))) or 1e-6
    audio = (audio / peak * 0.9).astype(np.float32)

    print("步骤 3/3  加载模型并识别（本地模型）...")
    model = WhisperModel(MODEL_DIR, device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio, language="zh",
                                      beam_size=5, vad_filter=True)
    text = "".join(s.text for s in segments).strip()

    print()
    print("=" * 52)
    print(f"识别结果: {text!r}")
    print(f"语言判定: {info.language}  置信度 {info.language_probability:.2f}")
    print("=" * 52)

    if text:
        speak(f"我听到的是：{text}")
    else:
        speak("没有识别到内容，请再试一次。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
