# -*- coding: utf-8 -*-
"""dressing_brief.py —— 「检测到耳机接入」时执行的一次性动作。

流程（顺序刻意如此，为了满足「弹窗 + 语音，播完自动关窗」）：
    1. 先把桌面的「穿衣建议.exe」拉起来（弹窗，你能看到界面）
    2. 同时取临沂实时天气（wttr.in，与 exe 同源）
    3. 拼出一段口语化的播报文本
    4. 交给 speaker_once.py，从【耳机】那个输出设备念出来
    5. 念完按窗口标题优雅关掉那个窗口（WM_CLOSE，兜底 taskkill）

为什么不让 exe 自己念：
    exe 是纯 GUI（tkinter --windowed 打包），不写文件、不输出 stdout，
    「它算出来的温度」拿不到。但我们有它的源码镜像 dressing_core.py，
    用同一套 OUTFITS / wttr.in / build_tips 自己算一遍，结果与窗口显示完全一致。

单独跑（调试用）:
    python dressing_brief.py            # 完整跑一遍：弹窗 + 播报 + 关窗
    python dressing_brief.py --dry      # 只打印将要念的文字，不弹窗、不出声、不关窗

依赖：dressing_core.py（上游镜像）、tts_core.py、speaker_once.py、config.json
"""

import os
import re
import sys
import json
import time
import ctypes
import subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

LOG_FILE = os.path.join(BASE_DIR, "dressing_brief.log")

# 默认值（config.json 里没有就用这些）
# 用 ~ 展开而不是写死 C:\Users\<名字>\... —— 换机器/换用户名都不用改
DEFAULT_EXE = os.path.join(os.path.expanduser("~"), "Desktop", "穿衣建议.exe")
DEFAULT_CITY = "临沂"
DEFAULT_WINDOW_TITLE = "穿衣建议"

DRY = "--dry" in sys.argv or "--dry-run" in sys.argv


# ----------------------------------------------------------------- 日志

def log(msg):
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass
    if DRY:
        print(msg)


# ----------------------------------------------------------------- 配置

def load_config():
    try:
        with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"[cfg] 读取 config.json 失败: {e}")
        return {}


def cfg_dressing(cfg):
    d = cfg.get("dressing_brief") or {}
    # expanduser：配置里写 "~/Desktop/穿衣建议.exe" 也能用
    return {
        "exe": os.path.expanduser(d.get("exe") or DEFAULT_EXE),
        "city": d.get("city") or DEFAULT_CITY,
        "window_title": d.get("window_title") or DEFAULT_WINDOW_TITLE,
        "launch_exe": d.get("launch_exe", True),
        "close_window": d.get("close_window", True),
        "detail": d.get("detail", "full"),   # full | brief
    }


# ----------------------------------------------------------------- 文本口语化

# 这些符号/emoji 念出来会变成噪音，先清掉
_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200d\u2b00-\u2bff]"
)


def speechify(s, drop_uv_bracket=True):
    """把给人看的排版文本，转成给 TTS 念的口语文本。

    '+ ' -> '加'，'/' -> '或'，'·' 与括号 -> 逗号，
    去掉 emoji，合并重复标点，去掉所有空白。
    """
    s = s or ""
    if drop_uv_bracket:
        s = re.sub(r"[（(]\s*UV\s*\d+\s*[)）]", "", s)
    s = _EMOJI.sub("", s)
    s = s.replace("（", "，").replace("）", "，")
    s = s.replace("(", "，").replace(")", "，")
    s = s.replace("+", "加").replace("/", "或").replace("·", "，")
    s = s.replace("℃", "度")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[，,]{2,}", "，", s)
    s = re.sub(r"[。]{2,}", "。", s)
    s = re.sub(r"^[，。、]+", "", s)
    s = re.sub(r"[，、]+$", "", s)
    return s.strip()


_CJK = re.compile(r"[\u4e00-\u9fff]")


def zh_desc(desc, core=None):
    """把天气描述补成中文（大小写不敏感）。

    为什么要这么一层：上游那份 WEATHER_ZH 是**大小写敏感**的，表里写
    "Partly cloudy" 而 wttr.in 有时返回 "Partly Cloudy"，就对不上、原样漏成英文，
    TTS 念出来是「帕特利 克劳迪」这种洋腔。
    这里只在**念之前**兜一道：已经是中文就不动，英文按大小写不敏感查表，
    查不到才原样返回。**不修改 dressing_core 那份上游镜像**（保持可重新同步）。
    """
    if not desc or _CJK.search(desc):
        return desc
    try:
        if core is None:
            import dressing_core as core
        table = core.WEATHER_ZH
    except Exception:
        return desc
    key = desc.strip().lower()
    for k, v in table.items():
        if k.strip().lower() == key:
            return v
    return desc


def greeting():
    h = datetime.now().hour
    if 5 <= h < 8:
        return "早上好"
    if 8 <= h < 11:
        return "上午好"
    if 11 <= h < 13:
        return "中午好"
    if 13 <= h < 18:
        return "下午好"
    if 18 <= h < 23:
        return "晚上好"
    return "夜深了"


# ----------------------------------------------------------------- 播报文本

def build_speech(core, w, city, detail="full", greet=True):
    """把天气数据拼成一段口语播报文本。

    greet=False 时去掉开头那句问候 —— 语音助手被问「今天天气怎么样」时
    直接答内容更自然，不需要先来一句「下午好」。
    """
    temp = w["temp"]
    outfit, base_tip = core.pick_outfit(temp)

    parts = []
    if greet:
        parts.append(greeting() + "。")

    # 温度 + 天气 + 体感
    seg = f"{city}今天{temp:.0f}度"
    if w.get("desc"):
        seg += f"，{zh_desc(w['desc'], core)}"
    feels = w.get("feels")
    if feels is not None:
        seg += f"，体感{float(feels):.0f}度"
    parts.append(seg + "。")

    # 环境：湿度 / 风 / 紫外线
    if detail == "full":
        env = []
        if w.get("humidity"):
            env.append(f"湿度{w['humidity']}%")
        if w.get("wind_kmph") is not None:
            dir_zh = core.WIND_DIR_ZH.get(w.get("wind_dir") or "", "")
            prefix = f"{dir_zh}风" if dir_zh else "风"
            env.append(f"{prefix}{core.wind_scale(w['wind_kmph'])}级")
        if w.get("uv") is not None:
            env.append(f"紫外线指数{w['uv']}，{core.uv_desc(w['uv'])}")
        if env:
            parts.append("，".join(env) + "。")

    # 建议搭配
    parts.append(f"建议穿{speechify(outfit)}。")

    # 小贴士（动态：雨/雪/大风/紫外线）
    tips = core.build_tips(base_tip, w.get("desc"), temp,
                           w.get("wind_kmph"), w.get("uv"))
    for t in (tips or "").split("\n"):
        t = speechify(t)
        if not t:
            continue
        if t.startswith("或") and parts:
            # 上游那句是接着搭配说的（「或长袖衬衫单穿…」），
            # 单独立句会变成「。或…」读起来很断，并进上一句更顺
            parts[-1] = parts[-1].rstrip("。") + "，" + t + "。"
        else:
            parts.append(t + "。")

    text = "".join(parts)
    text = re.sub(r"[，]{2,}", "，", text)
    return text


def build_fail_speech(city, err):
    return (f"{greeting()}。没能拿到{city}的天气，"
            f"穿衣建议暂时给不了。你可以双击桌面的穿衣建议看一眼。")


# ----------------------------------------------------------------- 启停 exe

CREATE_DETACHED = 0x00000008       # DETACHED_PROCESS
CREATE_NEW_GROUP = 0x00000200      # CREATE_NEW_PROCESS_GROUP
CREATE_NO_WINDOW = 0x08000000      # CREATE_NO_WINDOW

_DEVNULL = None


def launch_exe(exe):
    """脱管启动 exe。

    这里必须彻底脱管（DEVNULL + DETACHED）：exe 是 PyInstaller onefile，
    运行时会把真正干活的子进程留在后台。如果父进程抓着 stdout 管道不放，
    那个子进程会一直抱着管道，communicate() 永远不返回（上一轮踩过这个坑）。
    """
    global _DEVNULL
    if _DEVNULL is None:
        _DEVNULL = open(os.devnull, "wb")
    try:
        p = subprocess.Popen(
            [exe],
            cwd=os.path.dirname(exe),
            stdin=subprocess.DEVNULL,
            stdout=_DEVNULL,
            stderr=_DEVNULL,
            creationflags=CREATE_DETACHED | CREATE_NEW_GROUP | CREATE_NO_WINDOW,
            close_fds=True,
        )
        log(f"[exe] 已启动 {os.path.basename(exe)} (pid={p.pid})")
        return p
    except Exception as e:
        log(f"[exe] 启动失败: {type(e).__name__} {e}")
        return None


def _find_window(title):
    try:
        u32 = ctypes.windll.user32
        u32.FindWindowW.restype = ctypes.c_void_p
        return u32.FindWindowW(None, title)
    except Exception:
        return 0


def close_exe(exe, title, wait_sec=25):
    """按窗口标题优雅关闭；标题找不到就兜底 taskkill。"""
    u32 = ctypes.windll.user32
    u32.FindWindowW.restype = ctypes.c_void_p
    u32.PostMessageW.restype = ctypes.c_bool

    hwnd = 0
    t0 = time.time()
    while time.time() - t0 < wait_sec:
        hwnd = _find_window(title)
        if hwnd:
            break
        time.sleep(0.5)

    if hwnd:
        try:
            u32.PostMessageW(ctypes.c_void_p(hwnd), 0x0010, 0, 0)  # WM_CLOSE
            log(f"[exe] 已向窗口『{title}』发送关闭信号")
            # 给它 3 秒自己退，退不掉再强制
            time.sleep(3)
            if not _find_window(title):
                return True
        except Exception as e:
            log(f"[exe] WM_CLOSE 失败: {e}")
    else:
        log(f"[exe] 未找到窗口『{title}』，走 taskkill 兜底")

    try:
        subprocess.run(["taskkill", "/F", "/IM", os.path.basename(exe), "/T"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=CREATE_NO_WINDOW)
        log("[exe] taskkill 兜底完成")
    except Exception as e:
        log(f"[exe] taskkill 失败: {e}")
    return False


# ----------------------------------------------------------------- 播报

def python_for_speech():
    """播报用的解释器：优先 pythonw（不弹黑框），没有就退 python。"""
    exe = sys.executable or ""
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.exists(cand) else exe


def speak(text, cfg):
    """用 speaker_once.py 在独立进程的主线程里播报（这是唯一稳定出声的方式）。"""
    py = python_for_speech()
    script = os.path.join(BASE_DIR, "speaker_once.py")
    rate = str(cfg.get("rate", 185))
    volume = str(cfg.get("volume", 1.0))
    device = cfg.get("output_device", "") or ""

    cmd = [py, script, text, rate, volume, device]
    log(f"[tts] 播报({len(text)}字) 设备=『{device}』: {text}")
    if DRY:
        return True
    try:
        subprocess.run(cmd, cwd=BASE_DIR,
                       stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=CREATE_NO_WINDOW, timeout=180)
        return True
    except Exception as e:
        log(f"[tts] 播报失败: {type(e).__name__} {e}")
        return False


# ----------------------------------------------------------------- 主流程

def main():
    t_start = time.time()
    cfg = load_config()
    d = cfg_dressing(cfg)
    log("=" * 56)
    log(f"开始穿衣播报 (city={d['city']}, detail={d['detail']}, dry={DRY})")

    # 1) 先弹窗（用户要能看到界面）
    if d["launch_exe"] and not DRY and os.path.exists(d["exe"]):
        launch_exe(d["exe"])
    elif not os.path.exists(d["exe"]):
        log(f"[exe] 找不到 {d['exe']}，跳过弹窗")

    # 2) 取天气
    text = None
    try:
        import dressing_core as core
        w = core.fetch_weather(d["city"])
        log(f"[wx] {d['city']} {w['temp']:.0f}度 {w.get('desc')} "
            f"体感{w.get('feels')} 湿度{w.get('humidity')}% "
            f"风{w.get('wind_kmph')}km/h UV{w.get('uv')}")
        text = build_speech(core, w, d["city"], d["detail"])
    except Exception as e:
        log(f"[wx] 取天气失败: {type(e).__name__} {e}")
        text = build_fail_speech(d["city"], e)

    # 3) 播报
    speak(text, cfg)
    log(f"[tts] 播报结束，累计 {time.time() - t_start:.1f}s")

    # 4) 念完关窗
    if d["close_window"] and not DRY and d["launch_exe"]:
        close_exe(d["exe"], d["window_title"])
        log("[exe] 收尾完成")

    log(f"全部完成，总耗时 {time.time() - t_start:.1f}s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        try:
            log("[fatal] " + traceback.format_exc().replace("\n", " | "))
        except Exception:
            pass
        traceback.print_exc()
        sys.exit(1)
