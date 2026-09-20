# -*- coding: utf-8 -*-
"""notify.py —— 让「小助」响一声 / 说一句，提醒萌哥。

这是 WorkBuddy 侧的统一提醒入口。自动选路：
    助手在跑  -> 写进 notify.json 队列，助手在 1 秒内响铃 + 播报（声音最稳）
    助手没跑  -> 当场直接响铃 + 播报（尽力而为，可能被系统静默）

用法:
    python notify.py "任务做完了"                  # 直接播报
    python notify.py --chime "任务做完了"           # 先响铃(done)再播报  <- 最常用
    python notify.py --chime --kind soft "已完成"   # 指定铃声音色
    python notify.py --chime-only                  # 只响铃，不播报
    python notify.py --status                      # 助手在不在跑？队列里有什么？
    python notify.py --list                        # 只看队列
    python notify.py --clear                       # 清空队列

强制指定走哪条路:
    --queue    必须走队列（哪怕助手没跑，等它启动再放）
    --direct   必须当场放（不走队列）
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from chime_kinds import DEFAULT as DEFAULT_KIND          # noqa: E402
from chime_kinds import KINDS as CHIME_KINDS             # noqa: E402

NOTIFY_FILE = os.path.join(BASE_DIR, "notify.json")
HEARTBEAT_FILE = os.path.join(BASE_DIR, "assistant.heartbeat")
CHIME_PY = os.path.join(BASE_DIR, "chime.py")
SPEAK_ONCE = os.path.join(BASE_DIR, "speaker_once.py")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# 心跳超过这个秒数就认为助手没在跑
ALIVE_SEC = 15


# ---------------------------------------------------------------- 基础

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def output_device():
    return (load_json(CONFIG_FILE, {}).get("output_device") or "").strip()


def chime_volume():
    """铃声增益，取 config.json 的 chime_volume（原来这条路没传，等于白配）。"""
    try:
        return float(load_json(CONFIG_FILE, {}).get("chime_volume", 0.9) or 0.9)
    except Exception:
        return 0.9


def assistant_alive():
    """助手进程是否在跑（靠心跳文件的修改时间判断）。返回 (bool, 距今秒数)。"""
    try:
        age = time.time() - os.path.getmtime(HEARTBEAT_FILE)
        return age <= ALIVE_SEC, age
    except Exception:
        return False, None


def run_py(script, *args):
    """用当前解释器跑项目里的脚本，不弹黑窗，失败不抛。"""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run([sys.executable, script, *[str(a) for a in args]],
                       timeout=120, creationflags=flags)
        return True
    except Exception as e:
        print(f"[warn] 执行 {os.path.basename(script)} 失败: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------- 队列

def push(text, chime=None, chime_only=False):
    """往队列里追加一条。"""
    data = load_json(NOTIFY_FILE, {})
    if not isinstance(data.get("pending"), list):
        data["pending"] = []
    item = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    if text:
        item["text"] = text
    if chime:
        item["chime"] = chime
    if chime_only:
        item["chime_only"] = True
    data["pending"].append(item)
    save_json(NOTIFY_FILE, data)
    return item


def show_queue():
    data = load_json(NOTIFY_FILE, {})
    pending = data.get("pending") or []
    if not pending:
        print("队列为空。")
    else:
        print(f"待播 {len(pending)} 条：")
        for i, it in enumerate(pending, 1):
            chime = f" [铃声:{it.get('chime')}]" if it.get("chime") else ""
            only = " [只响铃]" if it.get("chime_only") else ""
            print(f"  {i}. {it.get('text', '')}{chime}{only}   ({it.get('ts', '')})")
    print(f"上次被助手读取: {data.get('last_read') or '（从未）'}")


# ---------------------------------------------------------------- 主流程

def main():
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("text", nargs="*", help="要播报的内容")
    p.add_argument("--chime", action="store_true",
                   help="响一声铃（音色用 --kind 指定，默认 done）")
    p.add_argument("--kind", default=DEFAULT_KIND, choices=list(CHIME_KINDS),
                   help=f"铃声音色: {' / '.join(CHIME_KINDS)}")
    p.add_argument("--chime-only", action="store_true", help="只响铃，不播报")
    p.add_argument("--status", action="store_true", help="查看助手状态与队列")
    p.add_argument("--list", action="store_true", help="只看队列")
    p.add_argument("--clear", action="store_true", help="清空队列")
    p.add_argument("--queue", action="store_true", help="强制走队列")
    p.add_argument("--direct", action="store_true", help="强制当场播")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="不输出任何内容（给 hook 用，避免污染对话）")
    args = p.parse_args()

    if args.quiet:
        # hook 的 stdout 会显示在对话里，必须闭嘴
        _devnull = open(os.devnull, "w", encoding="utf-8")
        sys.stdout = _devnull
        sys.stderr = _devnull

    if args.status:
        alive, age = assistant_alive()
        if alive:
            print(f"助手状态: 运行中（心跳 {age:.0f} 秒前）")
        elif age is None:
            print("助手状态: 未运行（没有心跳文件，可能从没启动过）")
        else:
            print(f"助手状态: 未运行（心跳停在 {age / 60:.1f} 分钟前）")
        print(f"输出设备: {output_device() or '（未设置，跟随系统默认）'}")
        print()
        show_queue()
        return 0

    if args.list:
        show_queue()
        return 0

    if args.clear:
        data = load_json(NOTIFY_FILE, {})
        data["pending"] = []
        save_json(NOTIFY_FILE, data)
        print("队列已清空。")
        return 0

    text = " ".join(args.text).strip()
    chime = args.kind if (args.chime or args.chime_only) else None

    if not text and not chime:
        p.print_help()
        return 1

    if args.chime_only:
        text = ""

    # ---- 选路 ----
    alive, _ = assistant_alive()
    if args.queue:
        use_queue = True
    elif args.direct:
        use_queue = False
    else:
        use_queue = alive

    if use_queue:
        push(text, chime=chime, chime_only=args.chime_only)
        if alive:
            print(f"已通知助手（队列）: {'[铃声]' if chime else ''}{text or '（只响铃）'}")
        else:
            print(f"助手没在跑，已入队等它启动: {text or '（只响铃）'}")
            print("  想立刻听到就双击桌面「小助语音助手.bat」，或加 --direct 当场放。")
        return 0

    # ---- 当场放 ----
    dev = output_device()
    if chime:
        run_py(CHIME_PY, chime, dev, "--volume", chime_volume())
    if text:
        run_py(SPEAK_ONCE, text, 185, 1.0, dev)
    print(f"已当场播放: {'[铃声]' if chime else ''}{text or '（只响铃）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
