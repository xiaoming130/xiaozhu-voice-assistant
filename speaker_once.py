# -*- coding: utf-8 -*-
"""speaker_once.py —— 念一句话就退出，可指定输出设备。

由 assistant.py 以子进程方式调用。
单独跑也可以: python speaker_once.py "要说的话" [语速] [音量] [输出设备]

输出设备参数（第 4 个，可省略）:
    传设备名的关键字，如 "耳机 (Realtek(R) Audio)"
    省略或传空 -> 跟随 Windows 默认播放设备
    匹配不到   -> 退回默认设备，并往 tts.log 记一行

存在的理由：pyttsx3 在主进程的工作线程里会「日志正常、但不出声」，
放到独立子进程的主线程里跑就正常。
输出设备定向由 tts_core 负责（pyttsx3 本身不带这个能力）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    if len(sys.argv) < 2:
        print("usage: speaker_once.py <text> [rate] [volume] [device]")
        return 1

    text = sys.argv[1]
    rate = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else 185
    volume = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else 1.0
    device = sys.argv[4] if len(sys.argv) > 4 else ""

    import pyttsx3

    import tts_core

    engine = pyttsx3.init("sapi5")
    engine.setProperty("rate", rate)
    engine.setProperty("volume", volume)
    for v in engine.getProperty("voices"):
        name = (v.name or "").lower()
        vid = (v.id or "").lower()
        if "chinese" in name or "zh-cn" in vid:
            engine.setProperty("voice", v.id)
            break

    # ---- 关键：把输出钉到指定设备 ----
    tts_core.resolve_and_log(engine, device)

    engine.say(text)
    engine.runAndWait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
