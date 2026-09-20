"""probe_selfhearing.py —— 测「麦克风能不能听见自己的播报」。

用途：assistant.py 启动时会先静默 1.5 秒校准底噪。如果这段时间正好有
提醒/通知在播报，校准就会被污染（实测出现过 噪声底 0.20861 / 95%位 1.00000，
阈值被 max_threshold 顶到 0.04500，等于白校）。

本探针按 assistant.py 完全相同的参数开流，边测边在旁边放音，
看 RMS 会不会被自己的声音拉起来。

用法：
    python probe_selfhearing.py            # 默认测 16 秒
    python probe_selfhearing.py 20         # 自定义秒数
"""
import json
import os
import subprocess
import sys
import threading
import time

import numpy as np
import sounddevice as sd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_cfg():
    try:
        with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def resolve_mic(cfg):
    """和 assistant.resolve_mic 同一套逻辑，避免测的不是同一个设备。"""
    if cfg.get("mic_device") is not None:
        return int(cfg["mic_device"])
    kws = cfg.get("mic_name_keywords", [])
    best = None
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] < 1:
            continue
        if all(k in d["name"] for k in kws):
            try:
                sd.check_input_settings(device=i, samplerate=16000,
                                        channels=1, dtype="float32")
                return i
            except Exception:
                best = best if best is not None else i
    return best


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 16.0
    cfg = load_cfg()
    dev = resolve_mic(cfg)
    if dev is None:
        print("找不到麦克风")
        return 1
    name = sd.query_devices(dev)["name"]
    device_out = cfg.get("output_device", "")
    print(f"录音设备: [{dev}] {name}")
    print(f"播报设备: {device_out or '(系统默认)'}")
    print()

    block = int(16000 * 0.03)
    level = {"rms": 0.0}
    playing = threading.Event()

    def cb(indata, frames, t, status):
        level["rms"] = float(np.sqrt(np.mean(indata[:, 0] ** 2)))

    stream = sd.InputStream(device=dev, samplerate=16000, channels=1,
                            dtype="float32", blocksize=block, callback=cb)
    stream.start()

    def play_once(kind, text=None):
        playing.set()
        try:
            if text:
                subprocess.run([sys.executable,
                                os.path.join(BASE_DIR, "speaker_once.py"),
                                text, "185", "1.0", device_out],
                               timeout=120)
            else:
                subprocess.run([sys.executable,
                                os.path.join(BASE_DIR, "chime.py"),
                                kind, device_out, "--volume", "0.9"],
                               timeout=60)
        except Exception as e:
            print(f"  播放失败: {e}")
        finally:
            playing.clear()

    print(f"观察 {seconds:.0f} 秒。t=3s 响铃，t=6s 念话。\n")
    print(f"{'t(s)':>6}  {'RMS':>8}   事件")
    print("-" * 40)

    t0 = time.time()
    fired = set()
    rows = []
    while time.time() - t0 < seconds:
        el = time.time() - t0
        if el >= 3 and "chime" not in fired:
            fired.add("chime")
            threading.Thread(target=play_once, args=("done",), daemon=True).start()
        if el >= 6 and "say" not in fired:
            fired.add("say")
            threading.Thread(target=play_once,
                             args=(None, "这是一句用来测试自听的通话内容"),
                             daemon=True).start()
        tag = "◀ 正在放音" if playing.is_set() else ""
        rows.append((el, level["rms"], tag))
        if int(el * 10) % 5 == 0:
            print(f"{el:6.1f}  {level['rms']:8.5f}   {tag}")
        time.sleep(0.1)

    stream.stop()
    stream.close()

    quiet = [r for el, r, _ in rows if el < 2.5]
    loud = [r for el, r, tag in rows if tag]
    print("\n" + "=" * 40)
    if quiet:
        base = float(np.percentile(quiet, 15))
        print(f"安静时 15% 分位   : {base:.5f}")
    if loud:
        print(f"放音时最大 RMS    : {max(loud):.5f}")
        print(f"放音时 95% 分位   : {float(np.percentile(loud, 95)):.5f}")
    else:
        print("放音期间没采到数据（可能都被 busy 丢了或队列空）")
    print()
    print("判读：")
    print("  放音时 RMS 明显抬高 → 麦克风能听见自己的播报，")
    print("    校准时若正在播报，底噪会被污染 → 阈值被顶到上限。")
    print("  放音时 RMS 仍贴近安静值 → 不构成污染，那次异常另有原因。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
