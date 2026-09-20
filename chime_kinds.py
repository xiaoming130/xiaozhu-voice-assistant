# -*- coding: utf-8 -*-
"""chime_kinds.py —— 铃声音色的**唯一来源**。

为什么单独一个文件：
    `chime.py`（合成播放）和 `notify.py`（通知入口）都要知道有哪些音色。
    如果各自维护一份清单，加音色时必然漏改一处 —— 实测就踩过：
    chime.py 加了 `ask`，notify.py 的白名单没跟上，argparse 直接拒绝，铃声不响。
    所以这里集中定义，两边都 import 它。

依赖极轻（纯常量），`notify.py` 走 hook 路径时 import 它不会拖慢速度
（**不要**去 import chime.py —— 那会连带拉起 numpy）。
"""

KINDS = ("done", "ask", "soft", "alert", "error")
DEFAULT = "done"

# 各音色的用途说明（给 --list 和文档用）
MEANING = {
    "done": "任务/回复完成（上行三音）",
    "ask": "我在向你提问（上行两音，疑问上扬）",
    "soft": "轻提醒（单音）",
    "alert": "引起注意（两声同音「叮咚」）",
    "error": "出错（下行两音）",
}
