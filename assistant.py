# -*- coding: utf-8 -*-
"""
assistant.py —— 常驻语音助手

三条能力:
  1. 你说 -> 它听  : 唤醒词「小助」+ 语音指令, 本地识别, 语音回应
  2. 它说 -> 你听  : 监视 notify.json, 任何写进去的消息自动播报
  3. 到点提醒      : reminders.json 里的定时任务, 到点自动出声

用法:
    python assistant.py              常驻运行(占用麦克风)
    python assistant.py --no-mic     只跑播报侧, 不占麦克风
    python assistant.py --say "你好"  直接播报一句话后退出

播报输出设备由 config.json 的 output_device 决定（见 tts_core.py）。

Ctrl+C 退出。
"""
import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, date, timedelta

import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "models", "faster-whisper-base")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
TASKS_FILE = os.path.join(BASE_DIR, "tasks.json")
REMINDERS_FILE = os.path.join(BASE_DIR, "reminders.json")
NOTIFY_FILE = os.path.join(BASE_DIR, "notify.json")
HEARTBEAT_FILE = os.path.join(BASE_DIR, "assistant.heartbeat")
LOG_FILE = os.path.join(BASE_DIR, "assistant.log")
QUESTIONS_FILE = os.path.join(BASE_DIR, "questions.md")

DEFAULT_CONFIG = {
    "model": "small",
    "hotwords": "小助，小助手，现在几点，今天有什么安排，提醒我，专注，取消，有什么提醒",
    "mic_name_keywords": ["麦克风阵列", "Realtek"],
    "mic_device": None,
    "wake_words": ["小助", "小助手"],
    "energy_margin": 2.2,
    "max_threshold": 0.045,
    "min_threshold": 0.004,
    "silence_sec": 0.9,
    "min_speech_sec": 0.35,
    "max_record_sec": 15,
    "followup_sec": 10,
    "rate": 185,
    "volume": 1.0,
    "output_device": "耳机 (Realtek(R) Audio)",
    "chime_volume": 0.9,
}

CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


# ---------------------------------------------------------------- 基础工具

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


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


def cn_to_int(s):
    """把 '八' '二十' '二十一' '15' 之类转成整数，失败返回 -1。"""
    s = (s or "").strip()
    if not s:
        return -1
    if s.isdigit():
        return int(s)
    if "十" in s:
        head, _, tail = s.partition("十")
        tens = CN_DIGITS.get(head, 1) if head else 1
        ones = CN_DIGITS.get(tail, 0) if tail else 0
        return tens * 10 + ones
    if all(c in CN_DIGITS for c in s):
        return int("".join(str(CN_DIGITS[c]) for c in s))
    return -1


PINYIN_INITIAL_MAP = (("zh", "z"), ("ch", "c"), ("sh", "s"),
                      ("j", "x"), ("q", "x"), ("n", "l"), ("f", "h"))


def norm_pinyin(p):
    """声母归一化，让 叫(jiao)/小(xiao)、住(zhu)/猪(zhou) 这类混读能对上。"""
    p = (p or "").lower()
    for a, b in PINYIN_INITIAL_MAP:
        if p.startswith(a):
            return b + p[len(a):]
    return p


def wake_split(text, wake_words):
    """定位唤醒词，返回 (是否命中, 指令起始字符下标)。

    优先精确匹配，匹配不上就做拼音模糊匹配 —— 实测 whisper 会把「小助」
    听成「小猪 / 小竹 / 小主 / 小朱 / 叫住 / 小周」，这些拼音全是 xiao + z*。
    """
    if not text:
        return False, 0
    for w in sorted(wake_words, key=len, reverse=True):
        if w in text:
            return True, text.index(w) + len(w)
    try:
        from pypinyin import lazy_pinyin
    except Exception:
        return False, 0
    py = [norm_pinyin(p) for p in lazy_pinyin(text)]
    for i in range(len(py) - 1):
        if py[i] == "xiao" and py[i + 1].startswith("z"):
            return True, min(i + 2, len(text))
    return False, 0


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        cfg.update(load_json(CONFIG_FILE, {}))
    else:
        save_json(CONFIG_FILE, DEFAULT_CONFIG)
    return cfg


# ---------------------------------------------------------------- 播报引擎

SPEAK_ONCE = os.path.join(BASE_DIR, "speaker_once.py")
CHIME_PY = os.path.join(BASE_DIR, "chime.py")


class Speaker:
    """串行播报 + 响铃。

    两种活儿共用一条队列，所以「先响铃、再念话」的顺序天然成立。

    TTS 不走本进程的线程，而是每次 fork 一个子进程去念。
    实测 pyttsx3 在本进程工作线程里会「日志正常、但不出声」；
    放到子进程主线程跑，行为就和已验证可用的 speak.py 一致。
    铃声同理走子进程（sounddevice 在子进程里更干净）。

    device: 输出设备关键字（见 config.json 的 output_device）。
            留空 = 跟随系统默认设备；匹配不到也退回默认（会记 tts.log）。
    """

    def __init__(self, rate=185, volume=1.0, device="", chime_volume=0.9):
        self.q = queue.Queue()
        self.busy = threading.Event()
        self.rate = rate
        self.volume = volume
        self.device = (device or "").strip()
        self.chime_volume = chime_volume
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _worker(self):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        while not self._stop.is_set():
            try:
                job = self.q.get(timeout=0.3)
            except queue.Empty:
                continue
            if job is None:
                break

            kind, payload = job
            self.busy.set()
            try:
                if kind == "chime":
                    subprocess.run(
                        [sys.executable, CHIME_PY, payload, self.device,
                         "--volume", str(self.chime_volume)],
                        timeout=60, creationflags=flags,
                    )
                else:
                    subprocess.run(
                        [sys.executable, SPEAK_ONCE, payload,
                         str(self.rate), str(self.volume), self.device],
                        timeout=180, creationflags=flags,
                    )
            except Exception as e:
                log(f"{'响铃' if kind == 'chime' else '播报'}失败: {e}")
            finally:
                self.busy.clear()

    def say(self, text):
        text = (text or "").strip()
        if text:
            log(f"[播报] {text}")
            self.q.put(("say", text))

    def chime(self, kind="done"):
        """响一声。kind: done / soft / alert / error。"""
        kind = (kind or "done").strip() or "done"
        log(f"[响铃] {kind}")
        self.q.put(("chime", kind))

    def wait_idle(self, timeout=30):
        end = time.time() + timeout
        while not self.q.empty() and time.time() < end:
            time.sleep(0.1)
        while self.busy.is_set() and time.time() < end:
            time.sleep(0.1)

    def stop(self):
        self._stop.set()
        self.q.put(None)


# ---------------------------------------------------------------- 语音识别

def model_dir_for(name):
    """优先用指定模型；文件缺失或还在下载中就退回 base。"""
    d = os.path.join(BASE_DIR, "models", f"faster-whisper-{name}")
    mb = os.path.join(d, "model.bin")
    if os.path.isfile(mb) and os.path.getsize(mb) > 50_000_000:
        return d
    return MODEL_DIR


def ensure_model(model_dir=MODEL_DIR):
    """本地没有识别模型就自动下载（base 约 140MB，只下一次）。

    克隆仓库后直接跑 assistant.py 也能用 —— models/ 不入库，
    所以首次运行必须能把权重拉下来，否则会以一个不存在的路径去加载模型而报错。
    """
    mb = os.path.join(model_dir, "model.bin")
    if os.path.isfile(mb) and os.path.getsize(mb) > 50_000_000:
        return model_dir                       # 已经下好了
    name = os.path.basename(model_dir).replace("faster-whisper-", "") or "base"
    try:
        from faster_whisper import download_model
    except Exception as e:                     # 没装 faster-whisper 就交给下面报错
        log(f"无法自动下载模型（{e}），将按原路径加载: {model_dir}")
        return model_dir
    os.makedirs(model_dir, exist_ok=True)
    log(f"本地缺少识别模型，首次下载 {name} 到 {model_dir}（约 140MB，只此一次）…")
    t = time.time()
    download_model(name, output_dir=model_dir)
    log(f"模型下载完成，耗时 {time.time() - t:.1f}s")
    return model_dir


class Recognizer:
    def __init__(self, model_dir=MODEL_DIR, hotwords=None):
        from faster_whisper import WhisperModel
        model_dir = ensure_model(model_dir)
        log(f"加载语音识别模型: {os.path.basename(model_dir)}")
        t = time.time()
        self.model = WhisperModel(model_dir, device="cpu", compute_type="int8")
        self.hotwords = hotwords
        log(f"模型就绪，耗时 {time.time() - t:.1f}s")

    def transcribe(self, audio_f32_16k):
        try:
            import zhconv
        except Exception:
            zhconv = None
        kw = {"language": "zh", "beam_size": 5, "vad_filter": True}
        if self.hotwords:
            kw["hotwords"] = self.hotwords
        segments, _ = self.model.transcribe(audio_f32_16k, **kw)
        text = "".join(s.text for s in segments).strip()
        text = re.sub(r"[，。！？、,.\s]+", "", text)
        if zhconv and text:
            text = zhconv.convert(text, "zh-cn")
        return text


def resolve_mic(cfg):
    """按名称关键字找麦克风，找不到就用配置里的索引。"""
    if cfg.get("mic_device") is not None:
        return int(cfg["mic_device"])
    import sounddevice as sd
    kws = cfg.get("mic_name_keywords", [])
    best = None
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] < 1:
            continue
        name = d["name"]
        if all(k in name for k in kws):
            # 优先 WASAPI/MME 里能开出 16k 的那个
            try:
                sd.check_input_settings(device=i, samplerate=16000,
                                        channels=1, dtype="float32")
                return i
            except Exception:
                best = best if best is not None else i
    return best


def pick_samplerate(device):
    import sounddevice as sd
    for fs in (16000, 32000, 44100, 48000):
        try:
            sd.check_input_settings(device=device, samplerate=fs,
                                    channels=1, dtype="float32")
            return fs
        except Exception:
            continue
    return int(sd.query_devices(device)["default_samplerate"])


def resample(audio, src_fs, dst_fs):
    if src_fs == dst_fs:
        return audio.astype(np.float32)
    n = int(len(audio) * dst_fs / src_fs)
    if n <= 1:
        return np.zeros(1, dtype=np.float32)
    return np.interp(np.linspace(0, len(audio) - 1, n),
                     np.arange(len(audio)), audio).astype(np.float32)


# ---------------------------------------------------------------- 指令处理

class Assistant:
    def __init__(self, cfg, use_mic=True):
        self.cfg = cfg
        self.use_mic = use_mic
        self.running = threading.Event()
        self.running.set()
        self.speaker = Speaker(cfg["rate"], cfg["volume"],
                               cfg.get("output_device"),
                               cfg.get("chime_volume", 0.9))
        self.focus_until = None
        self.last_active = 0.0
        self._notify_mtime = 0.0
        self._weather_busy = False     # 正在后台查天气时，别重复发起
        self.recognizer = None
        self.stream = None

    # ---------------- 播报侧 ----------------

    def speak(self, text):
        self.speaker.say(text)

    def poll_notify(self):
        """WorkBuddy 写进 notify.json 的消息，读出来播报并清空。

        每条可以是：
          {"text": "..."}                    只念
          {"text": "...", "chime": "done"}   先响铃再念
          {"chime": "soft", "chime_only":1}  只响铃不念
        """
        try:
            if not os.path.exists(NOTIFY_FILE):
                return
            mt = os.path.getmtime(NOTIFY_FILE)
            if mt <= self._notify_mtime:
                return
            self._notify_mtime = mt
            data = load_json(NOTIFY_FILE, {})
            pending = data.get("pending", [])
            if not pending:
                return
            for item in pending:
                if isinstance(item, dict):
                    text = (item.get("text") or "").strip()
                    chime = (item.get("chime") or "").strip()
                    only = bool(item.get("chime_only"))
                else:
                    text, chime, only = str(item).strip(), "", False
                if chime:
                    self.speaker.chime(chime)
                if text and not only:
                    self.speak(text)
            data["pending"] = []
            data["last_read"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_json(NOTIFY_FILE, data)
        except Exception as e:
            log(f"读取通知失败: {e}")

    def poll_reminders(self):
        """定时提醒。"""
        data = load_json(REMINDERS_FILE, {"reminders": []})
        items = data.get("reminders", [])
        if not items:
            return
        now = datetime.now()
        changed = False
        for r in items:
            if r.get("done"):
                continue
            try:
                when = datetime.strptime(r["at"], "%Y-%m-%d %H:%M")
            except Exception:
                r["done"] = True
                changed = True
                continue
            if when <= now:
                self.speak(r.get("text") or "到点了，该做事了。")
                r["done"] = True
                changed = True
        if changed:
            save_json(REMINDERS_FILE, data)

    def check_focus(self):
        if self.focus_until and datetime.now() >= self.focus_until:
            self.focus_until = None
            self.speak("专注时间结束，休息一下吧。")

    # ---------------- 指令路由 ----------------

    def route(self, text):
        """把识别出的文本变成动作。返回是否已处理。"""
        raw = text
        t = text

        # 报时
        if re.search(r"(几点|时间|现在.*钟)", t):
            now = datetime.now()
            self.speak(f"现在是{now.hour}点{now.minute:02d}分。")
            return True

        # 日期、星期
        if re.search(r"(几号|星期几|周几|哪一天|什么日子)", t):
            now = datetime.now()
            week = "一二三四五六日"[now.weekday()]
            self.speak(f"今天是{now.month}月{now.day}日，星期{week}。")
            return True

        # 自我介绍
        if re.search(r"(你是谁|你叫什么|能做什么|会做什么|有什么功能|会干啥)", t):
            self.speak("我是小助。能报时报日期、念今天的安排、查天气和冷热、"
                       "记定时提醒，还能帮你计时专注。")
            return True

        # 客套
        if re.search(r"(谢谢|多谢|感谢|辛苦了)", t):
            self.speak("不客气。")
            return True

        if re.search(r"(晚安|睡觉去)", t):
            self.speak("晚安，早点休息。")
            return True

        # 今日安排
        if re.search(r"(今天|今日).*(安排|任务|计划|做什么|干什么|干啥)", t) or t in ("今天", "今日安排"):
            self.speak(self.tasks_brief())
            return True

        # 停止专注
        if re.search(r"(停止|取消|结束).*(专注|计时|倒计时)", t) or t in ("停", "取消", "不用了", "算了"):
            if self.focus_until:
                self.focus_until = None
                self.speak("好的，已取消。")
            else:
                self.speak("现在没有在计时。")
            return True

        # 开始专注 N 分钟
        m = re.search(r"专注\s*(\d{1,3}|[零一二两三四五六七八九十]+)\s*分钟", t)
        if m:
            mins = cn_to_int(m.group(1))
            if mins and mins > 0:
                self.focus_until = datetime.now() + timedelta(minutes=mins)
                self.speak(f"好的，专注{mins}分钟，到点我叫你。")
                return True

        # 提醒我 X 点做 Y
        m = re.search(r"(?:提醒我|叫我|记一下)?\s*(早上|上午|中午|下午|傍晚|晚上|夜里|凌晨)?\s*"
                      r"(\d{1,2}|[零一二两三四五六七八九十]+)\s*[点:：]\s*"
                      r"(半|\d{1,2}|[零一二两三四五六七八九十]+)?\s*分?\s*(.*)", t)
        if m and re.search(r"(提醒|叫我|记一下)", t):
            period, hh, mm, rest = m.group(1), m.group(2), m.group(3), m.group(4)
            hour = cn_to_int(hh)
            minute = 30 if mm == "半" else (cn_to_int(mm) if mm else 0)
            if minute < 0:
                minute = 0
            if hour >= 0:
                if period in ("下午", "傍晚", "晚上", "夜里") and hour < 12:
                    hour += 12
                if period == "中午" and hour < 12:
                    hour += 12
                if period == "凌晨" and hour == 12:
                    hour = 0
                content = re.sub(r"^[的\s，,]+", "", rest) or "该做事了"
                now = datetime.now()
                when = now.replace(hour=hour % 24, minute=minute % 60,
                                   second=0, microsecond=0)
                if when <= now:
                    when += timedelta(days=1)
                data = load_json(REMINDERS_FILE, {"reminders": []})
                data.setdefault("reminders", []).append({
                    "id": datetime.now().strftime("%Y%m%d%H%M%S"),
                    "at": when.strftime("%Y-%m-%d %H:%M"),
                    "text": f"提醒你，{content}",
                    "done": False,
                })
                save_json(REMINDERS_FILE, data)
                self.speak(f"好的，{when.month}月{when.day}日{when.hour}点{when.minute:02d}分提醒你{content}。")
                return True

        # 查看提醒
        if re.search(r"(有什么|有哪些|看看|查).*提醒", t):
            data = load_json(REMINDERS_FILE, {"reminders": []})
            todo = [r for r in data.get("reminders", []) if not r.get("done")]
            if not todo:
                self.speak("目前没有待提醒的事项。")
            else:
                parts = [f"{len(todo)}条提醒。"]
                for r in todo[:5]:
                    wt = r["at"][5:].replace("-", "月").replace(" ", "日")
                    parts.append(f"{wt}，{r.get('text','')}。")
                self.speak("".join(parts))
            return True

        # 任务完成
        if re.search(r"(完成|做完|搞完|搞定|结束)了?", t) and len(t) <= 12:
            self.speak("任务完成，干得漂亮。")
            return True

        # 天气 / 冷热（语音问答）
        # 放在提醒之后，免得「提醒我明天带伞」被天气截胡；再排除提醒类措辞兜一道
        if not re.search(r"(提醒|叫我|记一下)", t):
            if re.search(r"(多少度|几度|温度|热不热|冷不冷|热吗|冷吗|热不热)", t):
                self.ask_weather("temp")
                return True
            if re.search(r"(天气|气象|下雨|下雪|带伞|穿什么|穿啥|怎么穿|紫外线|风大|阴天|晴天)", t):
                self.ask_weather("full")
                return True

        # 唤醒应答
        if re.search(r"(在吗|你好|小助)", t) and len(t) <= 10:
            self.speak("在的，你说。")
            return True

        return False

    # ---------------- 天气问答（和穿衣播报同一套数据源） ----------------

    def ask_weather(self, kind="full"):
        """被问天气/冷热时调用。后台线程去查，别把麦克风主循环卡住。

        kind: "full" = 完整（温度/天气/体感 + 湿度/风/紫外线 + 搭配 + 贴士）
              "temp" = 只讲冷热（温度 + 体感 + 冷热评价 + 搭配）
        """
        if self._weather_busy:
            self.speak("正在查天气，稍等一下。")
            return
        self._weather_busy = True
        self.speak("我看一下。")
        threading.Thread(target=self._weather_worker, args=(kind,),
                         daemon=True).start()

    def _weather_worker(self, kind):
        try:
            self._weather_answer(kind)
        except Exception as e:
            log(f"查天气失败: {type(e).__name__} {e}")
            self.speak("天气没查到，等会儿再问我。")
        finally:
            self._weather_busy = False

    def _weather_answer(self, kind="full"):
        """取天气 -> 拼话术 -> 播报。

        话术复用 dressing_brief 那一套，保证「念出来的字 = 穿衣窗口显示的字」。
        """
        import dressing_brief as brief
        import dressing_core as core

        city = ((self.cfg.get("dressing_brief") or {}).get("city")) or "临沂"
        w = core.fetch_weather(city)          # 内部 timeout=12s

        # 完整问「天气怎么样」→ 按配置的详略；
        # 只问「热不热/多少度」→ 精简版（省掉湿度/风/紫外线，直接给温度+搭配）
        if kind == "temp":
            detail = "brief"
        else:
            detail = ((self.cfg.get("dressing_brief") or {}).get("detail")) or "full"
        # greet=False：被问一句就答一句，不用先来一句「下午好」
        text = brief.build_speech(core, w, city, detail=detail, greet=False)

        log(f"[天气问答/{kind}] {text}")
        self.speak(text)

    def tasks_brief(self):
        data = load_json(TASKS_FILE, None)
        if not data:
            return "还没有任务清单文件。"
        today = date.today().isoformat()
        items = [x for x in data.get("tasks", [])
                 if not x.get("done") and (x.get("daily") or x.get("due") == today)]
        if not items:
            return "今天没有待办，可以自由安排。"
        parts = [f"今天有{len(items)}项。"]
        for i, x in enumerate(items, 1):
            tm = f"{x['time']}，" if x.get("time") else ""
            parts.append(f"第{i}项，{tm}{x['title']}。")
        return "".join(parts)

    @staticmethod
    def _worth_recording(text):
        """过滤识别噪声：太短的、或大量重复单字的（如「铁铁铁铁铁铁」）。"""
        if len(text) < 4:
            return False
        uniq = len(set(text))
        if uniq <= 2:
            return False
        # 单个字重复占比过半也算噪声
        from collections import Counter
        most = Counter(text).most_common(1)[0][1]
        if most / len(text) > 0.5:
            return False
        return True

    def _record_question(self, text):
        try:
            with open(QUESTIONS_FILE, "a", encoding="utf-8") as f:
                f.write(f"- [{datetime.now():%Y-%m-%d %H:%M}] {text}\n")
        except Exception:
            pass

    # ---------------- 监听侧 ----------------

    def run_mic(self):
        import sounddevice as sd
        self.recognizer = Recognizer(model_dir_for(self.cfg.get("model", "base")),
                                     hotwords=self.cfg.get("hotwords"))

        dev = resolve_mic(self.cfg)
        if dev is None:
            log("找不到可用麦克风，仅运行播报侧。")
            self.use_mic = False
            return
        fs = pick_samplerate(dev)
        name = sd.query_devices(dev)["name"]
        log(f"麦克风: [{dev}] {name}  @ {fs}Hz")

        block = int(fs * 0.03)          # 30ms 一块
        audio_q = queue.Queue()

        def cb(indata, frames, t, status):
            if self.speaker.busy.is_set():
                return                   # 自己说话时丢弃，防自听
            audio_q.put(indata[:, 0].copy())

        self.stream = sd.InputStream(device=dev, samplerate=fs, channels=1,
                                     dtype="float32", blocksize=block,
                                     callback=cb)
        self.stream.start()

        # 环境噪声校准
        log("校准环境噪声，请保持安静 1.5 秒...")
        noise = []
        t0 = time.time()
        while time.time() - t0 < 1.5:
            try:
                noise.append(float(np.sqrt(np.mean(audio_q.get(timeout=0.5) ** 2))))
            except queue.Empty:
                pass
        if noise:
            base = float(np.percentile(noise, 15))
            noise_hi = float(np.percentile(noise, 95))
        else:
            base, noise_hi = 0.001, 0.001
        thresh = base * self.cfg["energy_margin"] + 0.003
        thresh = max(min(thresh, self.cfg["max_threshold"]), self.cfg["min_threshold"])
        log(f"噪声底 {base:.5f} (95%位 {noise_hi:.5f})  触发阈值 {thresh:.5f}")
        self.speak("语音助手已启动，叫我小助。")

        silence_need = int(self.cfg["silence_sec"] * fs / block)
        min_frames = int(self.cfg["min_speech_sec"] * fs / block)
        max_frames = int(self.cfg["max_record_sec"] * fs / block)

        buf, silent, recording = [], 0, False
        last_level_log = 0.0

        while self.running.is_set():
            try:
                chunk = audio_q.get(timeout=0.5)
            except queue.Empty:
                continue
            rms = float(np.sqrt(np.mean(chunk ** 2)))

            if time.time() - last_level_log > 6:
                last_level_log = time.time()
                log(f"[电平] 当前 {rms:.4f} / 阈值 {thresh:.4f}")

            if not recording:
                if rms > thresh:
                    recording = True
                    buf = [chunk]
                    silent = 0
                continue

            buf.append(chunk)
            silent = silent + 1 if rms <= thresh else 0
            done = silent >= silence_need or len(buf) >= max_frames
            if not done:
                continue

            recording = False
            if len(buf) < min_frames:
                buf = []
                continue

            audio = np.concatenate(buf)
            buf = []
            audio = resample(audio, fs, 16000)
            peak = float(np.max(np.abs(audio))) or 1e-6
            audio = (audio / peak * 0.9).astype(np.float32)

            text = self.recognizer.transcribe(audio)
            if not text:
                continue
            log(f"[听到] {text}")

            now = time.time()
            hit_wake, cut = wake_split(text, self.cfg["wake_words"])
            in_followup = (now - self.last_active) < self.cfg["followup_sec"]

            if not (hit_wake or in_followup):
                log(f"[忽略] 未听到唤醒词: {text}")
                continue

            clean = text[cut:] if hit_wake else text
            clean = clean.strip("，,。. ")

            if not clean:
                self.last_active = now
                self.speak("在的，你说。")
                continue

            if self.route(clean):
                self.last_active = now
                continue

            # 有唤醒词才算「在跟它说话」；免唤醒窗口里的杂音一律静默
            if not hit_wake:
                log(f"[静默] 未匹配指令: {clean}")
                continue

            self.last_active = now
            log(f"[未识别指令] {clean}")
            if self._worth_recording(clean):
                self.speak("这个我还不太会，先给你记下来了。")
                self._record_question(clean)
            else:
                self.speak("没听清，你再说一遍？")

    # ---------------- 主流程 ----------------

    def touch_heartbeat(self):
        """刷新心跳文件。notify.py --status 靠它的修改时间判断助手在不在跑。"""
        try:
            with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
                f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass

    def run(self):
        log("=" * 50)
        log("语音助手启动")
        log(f"播报输出设备: {self.speaker.device or '系统默认'}"
            f"（实际生效设备见 tts.log）")
        try:
            self.touch_heartbeat()
            if self.use_mic:
                t = threading.Thread(target=self.run_mic, daemon=True)
                t.start()
                time.sleep(2)
            else:
                self.speak("播报模式已启动。")

            while self.running.is_set():
                self.touch_heartbeat()
                self.poll_notify()
                self.poll_reminders()
                self.check_focus()
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self):
        log("正在退出...")
        self.running.clear()
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
        except Exception:
            pass
        self.speaker.stop()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--no-mic", action="store_true", help="不占用麦克风，只播报")
    p.add_argument("--say", default=None, help="直接播报一句话后退出")
    args = p.parse_args()

    cfg = load_config()

    if args.say:
        sp = Speaker(cfg["rate"], cfg["volume"], cfg.get("output_device"),
                     cfg.get("chime_volume", 0.9))
        sp.say(args.say)
        sp.wait_idle()
        sp.stop()
        time.sleep(0.5)
        return 0

    a = Assistant(cfg, use_mic=not args.no_mic)
    a.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
