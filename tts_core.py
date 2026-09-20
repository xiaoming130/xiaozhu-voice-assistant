# -*- coding: utf-8 -*-
"""tts_core.py —— 播报输出设备定向。

为什么要这个文件：
    pyttsx3 没有「选择输出设备」的接口，默认跟着 Windows 的默认播放设备走。
    只要插拔耳机、切外放，声音就会跑偏。这里通过 pyttsx3 内部持有的
    SAPI ISpeechVoice 对象，显式把 AudioOutput 钉到指定设备上。

对外只暴露两个函数：
    apply_output(engine, device)  把输出钉到 device 指定的设备，返回实际用的设备名
    log_line(msg)                追一行到 tts.log

设备名按「模糊匹配」处理，顺序是：完全相等 > 去掉括号后相等 > 包含。
"""

import os
import re
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "tts.log")


# ---------------------------------------------------------------- 名字归一化

def norm(s):
    """小写 + 全角括号统一 + 去所有空白。"""
    s = (s or "").lower()
    s = s.replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", "", s)


def bare(s):
    """再进一步砍掉括号及其后面的修饰。

    『耳机 (Realtek(R) Audio)』->『耳机』。
    用「从第一个左括号起全砍」而不是配对括号，是为了兼容嵌套括号。
    """
    return re.sub(r"\(.*", "", norm(s))


def _score(want, have):
    """匹配打分：3=完全相等，2=去括号后相等，1=包含，0=不匹配。"""
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


# ---------------------------------------------------------------- 日志

def log_line(msg):
    """追加一行到 tts.log（失败就算了，不能因为日志让播报挂掉）。"""
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------- 设备定向

def get_sapi(engine):
    """从 pyttsx3 Engine 里掏出底层 SAPI ISpeechVoice。

    路径 engine.proxy._driver._tts 是私有属性，pyttsx3 换版本可能变，
    所以取不到就返回 None，调用方退回「跟随系统默认」。
    """
    try:
        return engine.proxy._driver._tts
    except Exception:
        return None


def list_outputs(engine):
    """列出底层 SAPI 能看到的输出目标，返回 [(idx, desc), ...]。"""
    tts = get_sapi(engine)
    if tts is None:
        return []
    out = []
    try:
        coll = tts.GetAudioOutputs()
        for i in range(coll.Count):
            try:
                out.append((i, coll.Item(i).GetDescription()))
            except Exception:
                out.append((i, "<读取失败>"))
    except Exception:
        return []
    return out


def current_output(engine):
    """当前实际使用的输出设备名，读不到返回 None。"""
    tts = get_sapi(engine)
    if tts is None:
        return None
    try:
        return tts.AudioOutput.GetDescription()
    except Exception:
        return None


def apply_output(engine, device):
    """把播报输出钉到 device 指定的设备。返回实际生效的设备名。

    device 为空            -> 不动，跟随系统默认，返回 None
    device 匹配不到任何设备 -> 不动，退回系统默认，返回 None（调用方负责记日志）
    """
    device = (device or "").strip()
    if not device:
        return None

    tts = get_sapi(engine)
    if tts is None:
        return None

    try:
        coll = tts.GetAudioOutputs()
    except Exception:
        return None

    want = norm(device)
    best = None  # (score, token, desc)
    for i in range(coll.Count):
        tok = coll.Item(i)
        try:
            desc = tok.GetDescription() or ""
        except Exception:
            continue
        sc = _score(want, norm(desc))
        if sc > (best[0] if best else 0):
            best = (sc, tok, desc)

    if best is None:
        return None

    try:
        tts.AudioOutput = best[1]
    except Exception:
        return None

    # 读回确认，避免「以为设上了，其实没设」
    try:
        return tts.AudioOutput.GetDescription()
    except Exception:
        return best[2]


def resolve_and_log(engine, device):
    """apply_output 的带日志版：把结果写进 tts.log，返回实际设备名。"""
    engine_device = current_output(engine)
    used = apply_output(engine, device)
    want = (device or "").strip()

    if not want:
        log_line(f"[out] 系统默认: {engine_device or '?'}（未指定 output_device）")
        return engine_device

    if used is None:
        log_line(f"[out] 未匹配到『{want}』，已退回系统默认: {engine_device or '?'}")
        return engine_device

    exact = norm(used) == norm(want)
    tag = "命中" if exact else "近似命中"
    log_line(f"[out] {tag}: {used}")
    return used
