# -*- coding: utf-8 -*-
"""
speak.py —— 语音播报引擎（Windows SAPI / 外接喇叭）

用法:
    python speak.py "直接播报的文本"
    python speak.py --file 某文件.txt
    python speak.py --tasks              播报今日任务清单
    python speak.py --done "任务名"       播报"任务完成"
    python speak.py --list-voices        列出可用语音
    python speak.py --rate 190 "语速可调"

参数:
    --voice zh|en    选择中文/英文音色
    --rate  N        语速, 默认 185 (正常偏快)
    --volume N       音量 0.0~1.0, 默认 1.0
    --device 名字    指定输出设备(默认取 config.json 的 output_device)
                     留空字符串则跟随系统默认设备
"""
import argparse
import json
import os
import sys
from datetime import date, datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TASKS_FILE = os.path.join(BASE_DIR, "tasks.json")
LOG_FILE = os.path.join(BASE_DIR, "speak.log")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

sys.path.insert(0, BASE_DIR)


def log(msg: str) -> None:
    """追加一条播报日志，方便日后查有没有漏报。"""
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def pick_voice(engine, lang: str):
    """按语言挑音色，挑不到就用系统默认。"""
    want = "zh" if lang == "zh" else "en"
    try:
        for v in engine.getProperty("voices"):
            name = (v.name or "").lower()
            vid = (v.id or "").lower()
            if want == "zh" and ("chinese" in name or "zh-cn" in vid):
                engine.setProperty("voice", v.id)
                return v.name
            if want == "en" and ("zira" in name or "en-us" in vid):
                engine.setProperty("voice", v.id)
                return v.name
    except Exception:
        pass
    return "default"


def build_engine(rate: int, volume: float, lang: str):
    import pyttsx3
    engine = pyttsx3.init("sapi5")
    engine.setProperty("rate", rate)
    engine.setProperty("volume", volume)
    voice_name = pick_voice(engine, lang)
    return engine, voice_name


def load_tasks():
    """读取 tasks.json。"""
    if not os.path.exists(TASKS_FILE):
        return None
    with open(TASKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_output_device():
    """从 config.json 读 output_device；读不到返回空串（=系统默认）。"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return (json.load(f).get("output_device") or "").strip()
    except Exception:
        return ""


def tasks_text(which: str = "today") -> str:
    """把任务清单拼成适合朗读的中文句子。"""
    data = load_tasks()
    if data is None:
        return "还没有任务清单文件。"
    today = date.today().isoformat()
    items = [t for t in data.get("tasks", []) if not t.get("done")]

    if which == "today":
        items = [t for t in items if t.get("due") == today or t.get("daily")]
        head = f"今天是{date.today().month}月{date.today().day}日。"
    else:
        head = "当前未完成的任务有："

    if not items:
        return head + "今天没有待办任务，可以自由安排。"

    lines = [head, f"一共 {len(items)} 项。"]
    for i, t in enumerate(items, 1):
        tag = ""
        if t.get("time"):
            tag = f"{t['time']}，"
        lines.append(f"第{i}项，{tag}{t['title']}。")
    return "".join(lines)


def done_text(title: str, remaining: int) -> str:
    """任务完成时的播报词。"""
    base = f"任务完成：{title}。"
    if remaining > 0:
        return f"{base}还剩 {remaining} 项，继续加油。"
    return f"{base}今天的所有任务都清空了，干得漂亮！"


def main():
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("text", nargs="?", default=None, help="要播报的文本")
    p.add_argument("--file", dest="file", default=None, help="从文件读取文本")
    p.add_argument("--tasks", action="store_true", help="播报今日任务")
    p.add_argument("--all", action="store_true", help="播报全部未完成任务")
    p.add_argument("--done", dest="done", default=None, help="播报任务完成")
    p.add_argument("--list-voices", action="store_true")
    p.add_argument("--voice", default="zh", choices=["zh", "en"])
    p.add_argument("--rate", type=int, default=185)
    p.add_argument("--volume", type=float, default=1.0)
    p.add_argument("--device", default=None,
                   help="输出设备关键字；默认取 config.json 的 output_device")

    args = p.parse_args()

    # ---- 组装要读的文本 ----
    if args.list_voices:
        import pyttsx3
        e = pyttsx3.init("sapi5")
        for v in e.getProperty("voices"):
            print(v.name)
        return 0

    say_text = None
    if args.text:
        say_text = args.text
    elif args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            say_text = f.read().strip()
    elif args.tasks:
        say_text = tasks_text("today")
    elif args.all:
        say_text = tasks_text("all")
    elif args.done:
        data = load_tasks() or {"tasks": []}
        remaining = len([t for t in data.get("tasks", []) if not t.get("done")])
        say_text = done_text(args.done, max(remaining - 1, 0))
    else:
        p.print_help()
        return 1

    if not say_text:
        print("没有可播报的内容。")
        return 1

    # ---- 播报 ----
    engine, voice_name = build_engine(args.rate, args.volume, args.voice)
    print(f"[voice] {voice_name}")

    # 输出设备：命令行优先，其次 config.json，最后系统默认
    device = args.device if args.device is not None else load_output_device()
    import tts_core
    used = tts_core.resolve_and_log(engine, device)
    print(f"[out] {used or '系统默认'}")

    print(f"[say] {say_text}")
    engine.say(say_text)
    engine.runAndWait()
    log(say_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
