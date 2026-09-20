# 外接麦克风语音助手（小助）

让电脑用**指定输出设备出声**提醒你，用**麦克风听懂你说话**。
当前播报锁定在 **耳机 (Realtek(R) Audio)**，不会跑到外放去。

---

## 安装（首次使用）

要求 **Windows 10/11 + Python 3.10 以上**。

```bat
git clone https://github.com/xiaoming130/xiaozhu-voice-assistant.git
cd xiaozhu-voice-assistant
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy config.example.json config.json
```

然后双击 `start_assistant.bat`。**首次启动会自动下载语音识别模型**
（base 版约 140MB，下到 `models/`，只此一次），听到
「语音助手已启动，叫我小助」就成了。

> **`config.json` 不在仓库里**（`.gitignore` 已排除 —— 它记着你本机的设备名和路径）。
> 所以要先从 `config.example.json` 复制一份，再按下面的「配置」改。
> 仓库里 `models/`、运行日志、语音记录也都不入库。
>
> **改完 `config.json` 要重启助手才生效。**

想让它跟着电脑开机自动起，见下面的「④」「⑤」和 `watch_ctl.py`。

---

## 快速开始

| 我想干什么 | 怎么做 |
|---|---|
| **启动助手（最常用）** | **双击项目里的 `start_assistant.bat`**（嫌麻烦可以给它建个桌面快捷方式） |
| 从命令行启动 | `python assistant.py`，或 `assistant.py --no-mic` 只跑播报侧 |
| **让 WorkBuddy 干完活响一声** | 已自动（`Stop` hook），响完还会说「任务完成」，见下面「④」 |
| **让 WorkBuddy 提问时也响** | 已自动（`PreToolUse` hook），见下面「④」 |
| **打开 WorkBuddy 后自动播天气/穿衣** | 已自动（启动文件夹 .bat → `dressing_boot.py`），见下面「⑤」 |
| **提示音太小 / 想调大音量** | `volume_ctl.py` 看当前值，`volume_ctl.py 70` 设为 70% |
| 手动提醒我一下 | `notify.py --chime "事情办完了"` |
| 试听"提问"铃声 | `chime.py ask` |
| 只响铃不念话 | `notify.py --chime-only` |
| 问问助手在不在跑 | `notify.py --status` |
| 只想让它念一句话 | `speak.bat "要念的内容"` |
| 试听铃声 | `chime.py --list` 看音色，`chime.py done` 试听 |
| **看播报从哪个设备出声** | 跑 `device_probe.py`（列出全部输出设备） |
| 看每次播报实际用了哪个设备 | 看 `tts.log` |
| 检查声音通道 | 跑 `audio_check.py`（三层分层诊断） |
| 检查麦克风电平 | 跑 `mic_probe.py`（扫描全部录音设备） |
| 测语音识别准不准 | 跑 `stt_test.py` |

启动后听到「语音助手已启动，叫我小助」就成了。**窗口别关**，关掉即停止。

> PowerShell 里直接敲 `start_assistant.bat` 会报「无法识别为 cmdlet」——
> 要写成 `.\start_assistant.bat`，或者干脆双击。

---

## 能说什么

唤醒词 **小助**。实测它常听成「小猪 / 小竹 / 小主 / 小朱 / 叫住 / 小周」,
这些**都已用拼音模糊匹配兜住**，都能唤醒。

| 你说 | 它做 |
|---|---|
| 小助，现在几点 | 报时 |
| 小助，今天几号 / 今天星期几 | 报日期 |
| **小助，今天天气怎么样 / 天气咋样** | **念临沂天气 + 湿度/风/紫外线 + 穿衣建议（和穿衣窗口同一套数据）** |
| **小助，今天热不热 / 冷不冷 / 现在多少度** | **只讲冷热：温度 + 体感 + 该穿什么** |
| 小助，今天有什么安排 | 念当天待办 |
| 小助，提醒我八点做作业 | 存入提醒队列，到点自动出声 |
| 小助，专注 25 分钟 | 开始计时，到点提醒休息 |
| 小助，停 | 取消计时 |
| 小助，有什么提醒 | 列出未触发的提醒 |
| 小助，你是谁 | 自我介绍 |
| 小助，谢谢 | 回应客套 |
| 做完了 | 播报鼓励 |

唤醒后 **10 秒内**可以接着说话，不用反复叫。

**关键行为**：只有带唤醒词时才算「在跟它说话」。免唤醒窗口里的杂音、
视频声一律**静默忽略**，既不播报也不记录 —— 不会像早期版本那样逢人就接话。

> **天气问答**走的是和「穿衣播报」**同一套逻辑**（`dressing_core.py` + `dressing_brief.build_speech`），
> 所以念出来的和桌面窗口显示的是**同一份数据**。查天气放在**后台线程**，不会卡住麦克风循环
> （先说一句「我看一下」，查到再接着念）。
> 数据源 `wttr.in`，城市取 `config.json` 的 `dressing_brief.city`（临沂）。
> 改完 `assistant.py` / `config.json` 要**重启助手**才生效（双击 `start_assistant.bat`）。

---

## 五条链路

**① 你 → 它（麦克风）**
麦克风 → 本地语音识别（faster-whisper）→ 指令动作。**全程离线，不联网。**

**② 它 → 你（喇叭）**
播报内容通过**独立子进程**调 Windows 中文语音（Huihui），
**只从 `config.json` 里 `output_device` 指定的设备出声**（当前 = 耳机 (Realtek(R) Audio)）。

默认值就是「耳机 (Realtek(R) Audio)」。想换设备：跑 `device_probe.py` 看名字，
改 `config.json` 的 `output_device`，重启助手。**留空则跟随系统默认设备。**

> ⚠️ 关键：pyttsx3 本身**不支持选择输出设备**，只会跟着 Windows 默认设备走，
> 插拔耳机声音就跑到外放去了。所以这里通过底层 SAPI 的 `AudioOutput` 显式钉住设备，
> 逻辑在 `tts_core.py`。找不到指定设备时**自动退回系统默认**，并往 `tts.log` 记一行。

> 为什么用子进程：pyttsx3 在本进程的工作线程里会「日志正常、但不出声」，
> 放进子进程主线程才稳。这是踩过的坑。

**③ 我 → 你（WorkBuddy 推消息）**
统一入口是 `notify.py`。它自动选路：

```
助手在跑  -> 写进 notify.json 队列，助手 1 秒内响铃/播报（声音最稳）
助手没跑  -> 当场直接响铃/播报（已实测能出声，见下）
```

```bash
python notify.py --chime "任务做完了，回来看看"   # 先响铃再念（最常用）
python notify.py "任务做完了"                   # 只念
python notify.py --chime-only                   # 只响铃
python notify.py --status                       # 助手在不在跑？队列里有什么？
```

队列条目长这样（助手读完自动清空，不用管 `last_read`）：

```json
{
  "pending": [
    { "text": "任务完成了，回来看看结果。", "chime": "done", "ts": "2026-09-18 20:40:09" }
  ]
}
```

**④ WorkBuddy 自动提醒（两个 hook）**

| 时机 | hook 事件 | 铃声 | 含义 |
|---|---|---|---|
| 我回复结束 | `Stop` | `done`（上行三音）**+ 说「任务完成」** | 「这一轮我说完了」 |
| **我向你提问** | `PreToolUse`，matcher `AskUserQuestion\|ExitPlanMode` | `ask`（上行两音） | **「我在问你，需要你回答」** |

两种铃声**音高和音数都不同**，不用看屏幕也能分辨是"办完了"还是"在问你"。
`done` 还会**补一句「任务完成」**（`ask` 只响铃）。

> **想改「说完话之后说什么」**：只改 `~/.workbuddy/hooks/wb-chime.py` 顶部的 **`SAY` 表**
> （`{"done": "任务完成", "ask": ""}`；**空串 = 只响铃不说话**）。
> 话术必须写在 Python 源文件里（UTF-8 安全），**别往 `settings.json` 命令行塞中文**。
> 改完立即生效，不用重启。加了语音后 hook 的 `timeout` 需要调大（现为 **30**，
> wb-chime.py 内部子进程超时是 20，外层必须更大）。

**实测（2026-09-18 20:55，萌哥确认听到了）**：助手**没开**的情况下，hook 依然
正常触发（日志有记录），且**铃声真的从耳机出来了**——所以不点开小助也能收到提醒。

> 准确的结论是：**前台/被等待**的进程能正常出声；只有**后台长驻**进程会被静默。
> 所以启动播报进程要用 `subprocess.run()` 同步等待，别 `Popen()` 就不管。

- 配置：`~/.workbuddy/settings.json` 的 `hooks.Stop` / `hooks.PreToolUse`
- 命令：`~/.workbuddy/hooks/wb-chime.py`（**全 ASCII 路径**，见下方说明）
- 日志：`~/.workbuddy/hooks/wb-chime.log`
- 备份：改前的配置存在 `~/.workbuddy/settings.json.bak-20260918`（最新一次：`.bak-20260919`）

五种铃声（`chime.py`，numpy 合成、走同一只耳机）：

| 音色 | 时长 | 用途 |
|---|---|---|
| `done` | 0.58s | 任务/回复完成，上行三音（默认） |
| `ask` | 0.47s | **我在提问**，上行两音（疑问上扬） |
| `soft` | 0.24s | 轻柔单音，只要个存在感 |
| `alert` | 0.41s | 两声同音，像「叮咚」 |
| `error` | 0.47s | 下行两音，报错 |

> ⚠️ **为什么要中间隔一层 `wb-chime.py`**：hook 命令由 WorkBuddy 交给
> **Git Bash** 执行，而本项目路径含中文（「外接麦克风」）。中文路径写进
> `settings.json` 再传给 bash 有编码翻车风险，所以用**全 ASCII 路径**的转发脚本兜底，
> Python 源文件里的中文路径不受影响。脚本收一个参数指定音色（`done` / `ask`）。
>
> ⚠️ hook 的 stdout 会显示在对话里，所以转发脚本加了 `--quiet`，**绝不打字**。
>
> ⚠️ **音色清单只有一处定义**（`chime_kinds.py`）：`chime.py` 和 `notify.py` 都 import 它，
> 且 `chime.py` 启动时有 `assert` 卡一致性。
> 起因：加 `ask` 时只改了 `chime.py`，`notify.py` 的白名单没跟上，
> argparse 直接拒绝（rc=2）、铃声不响 —— 这个坑不能再踩第二次。

**⑤ 打开 WorkBuddy 后 → 自动播「今天穿什么」（2026-09-19 新增）**

**触发**：**等 WorkBuddy 起来后自动播一次**（启动文件夹的 .bat 拉起 `dressing_boot.py`，
脚本内部等 `WorkBuddy.exe` 进程出现，再走后续流程）。

> WorkBuddy 本身设了开机自启，所以实际效果就是「**WorkBuddy 一打开就播**」。
> 比死等固定秒数更稳 —— 等的是它**真的起来了**，而不是拍一个 20 秒的脑门数字。
> 切回老行为：把 `config.json` 的 `dressing_boot.trigger` 改成 `"boot"` 即可。

> ⚠️ **为什么不按「耳机接入」触发**（这是踩过的设计错）：
> 最初做的就是监听「`耳机 (Realtek(R) Audio)` 接入」。但这只耳机**一直插在电脑上**——
> 设备从开机起就常驻在场，「不在场 → 在场」这个**边沿永远不会再发生**，
> 监听器等于**永远不触发**。所以改成**由外部时机触发**，反而更简单：
> 不需要任何常驻进程，跑完即退、零内存占用，也顺带绕开了沙箱回收进程的麻烦。
> `headphone_watch.py` 仍然保留 —— 它只在「耳机**经常插拔**」时才有意义（见下方开关）。

**动作**（全自动，约 32 秒）：

```
先静默 5s（让桌面/音频栈起来）
        ↓
等 WorkBuddy.exe 进程出现（超时 300s；等不到就本次不播）
        ↓
等网络就绪（探 wttr.in，超时 120s）
        ↓
等音频设备就绪（设备常驻时秒过，超时 45s）
        ↓
启动桌面「穿衣建议.exe」弹窗
        ↓ 同时
取临沂实时天气（wttr.in）
        ↓
耳机念出：温度 + 天气 + 体感 + 湿度/风/紫外线 + 建议搭配 + 小贴士
        ↓ 念完
自动关掉那个窗口（不留残窗、不留进程）
```

**实测时间线**（2026-09-19 19:43 真机跑通，trigger=workbuddy）：
`t=0` 启动 → `t=5s` 等到 WorkBuddy（0s 命中）→ 网络 0s → 设备在场 →
`t=32.1s` 播报结束，**退出码 0、零残留进程**。

**实测播报样例**（2026-09-19 15:53）：

> 下午好。临沂今天 29 度，阴，体感 29 度。湿度 45%，东风 2 级，紫外线指数 3，有点晒。
> 建议穿短袖 T 恤加短裤或短裙。炎热，注意防晒补水。

> ⚠️ **为什么要抄一份逻辑**：那个 exe 是 `--windowed` 打包的纯 GUI，
> **不写文件、不输出 stdout**，算出来的温度根本抓不到（源码一开始也没在本机找到）。
> 后来在 GitHub 上找到了它 —— **`xiaoming130/dressing-advice`**。
> 于是按原文落了一份 `dressing_core.py` 做镜像，用**同一个 wttr.in、同一张 OUTFITS 温度表、
> 同一个 `build_tips`** 自己算一遍，保证**念出来的字和窗口里显示的字一致**。
> exe 仍然照常弹出来给你看，只是「念」这件事由小助接管。
> 上游若更新，重新拉 `dressing_advice.py` 覆盖 `dressing_core.py` 即可。

> ⚠️ **为什么用 SAPI 枚举探设备**：`sounddevice`(PortAudio) 的设备表是**进程启动时的快照**，
> 插拔耳机不会刷新，得 `_terminate/_initialize` 才能重读，又重又慢；而 SAPI 的
> `GetAudioOutputs()` **每次调用都是实时重枚举**，口径还正好和播报用的那一层一致。
> 轮询间隔 5s，一次枚举约 0.35s，开销可忽略。

> ⚠️ **为什么关键词要「全部命中」**：这台机器上不止一副耳机 ——
> `扬声器 (Realtek(R) Audio)`（外放口）、`耳机 (HG9086WS)`（另一副蓝牙）都在。
> 只认「耳机」会误命中 HG9086WS，只认「Realtek」会误命中扬声器，
> 所以 `must_include = ["耳机", "Realtek"]` 缺一不可。

常用命令：

```bash
python dressing_boot.py             # 手跑一次「等 WorkBuddy → 播报」全流程（含等待）
python dressing_boot.py --now       # 跳过等待，立刻播一次
python dressing_brief.py --dry      # 只打印将要念的文字，不弹窗不出声
python watch_ctl.py boot            # 同上（走控制面板）
python watch_ctl.py status          # 看配置全貌：触发条件 / 城市 / 弹窗 / 自启
python watch_ctl.py autostart on|off # 开机自启开关（还有 watch 模式，见下）
```

双击也能用：

| 双击 | 作用 |
|---|---|
| `play_once.bat` | **立刻播一次**（不用重启电脑就能验证） |
| `probe_headphone.bat` | 耳机状态探针（排查用，见下方「为什么不能按耳机开关触发」） |
| `start_watch.bat` / `stop_watch.bat` | 启停**可选**的「耳机插拔监听」 |

> ⚠️ **为什么不能按「耳机电源开关」触发**（2026-09-19 实测）：
> 这只耳机是**自带电源开关**的，但它设备**一直在设备列表里**，
> 开不开开关都能找到。为了查清有没有别的信号，写了 `device_state_probe.py`
> 做**全量监听**：把**全部 57 个音频端点**的状态（Active / Unplugged / NotPresent /
> Disabled）+ 当前默认输出设备，每秒快照一次、整体比对。
> **结果：104 次采样、0 处变化** —— 也就是说耳机的电源开关在 Windows 音频层
> **完全不可见**（物理上也说得通：耳机是插在 Realtek 的 3.5mm 模拟口上，
> 系统只看得见「那个孔插着东西」，看不见孔后面那副耳机通没通电）。
> 所以最终定为**按登录时机触发**（A 方案），这也是唯一可靠的自动触发点。

> 💡 顺带一个知识点：`sounddevice` 和 **SAPI** 列出的设备**不反映插拔状态**
> （这正是「开不开都能找到」的原因）；只有 **Core Audio 的端点状态**（pycaw 读的
> 那个）才区分 Active / Unplugged / NotPresent。所以真要检测插拔，得用后者。

> ⚠️ **自启为什么放「启动文件夹」而不是注册表 Run 键**（2026-09-19 实测结论）：
> 这台机器上 **Run 键有守护程序**，写进去会被静默回滚 —— 对照实验很干净：
> 同时写 `HKCU\Software\XiaozhuProbe` 和 `HKCU\...\CurrentVersion\Run`，
> 前者留住了（`probe = hello`），后者查无此项。典型的国产安全套件行为。
> 所以改用启动文件夹里的一个 `.bat`（**GBK 编码**写入，cmd.exe 在中文 Windows 上按 936 读）。
> 另外沙箱环境里 spawn 出来的常驻进程会被回收，所以正式启用请**重新登录一次**，
> 或自己双击 `start_watch.bat`。

---

## 文件说明

```
外接麦克风/
├─ assistant.py          常驻语音助手（主程序）
├─ start_assistant.bat   启动助手
├─ notify.py             **提醒统一入口**（自动选路：队列 / 当场放）
├─ speak.py / speak.bat  单次播报
├─ speaker_once.py       播报子进程（助手内部调用，也可单独跑）
├─ chime.py              铃声（numpy 合成，走同一只耳机）
├─ chime_kinds.py        音色清单的唯一来源（chime.py / notify.py 共用）
├─ tts_core.py           输出设备定向（把播报钉到指定设备）
├─ dressing_boot.py      **链路⑤ 主入口**：等 WorkBuddy 起来后播一次
├─ dressing_brief.py     一次性动作：弹窗+取天气+播报+关窗
├─ dressing_core.py      穿衣逻辑镜像（上游 dressing-advice 原文，与 exe 同源）
├─ play_once.bat         立刻播一次（双击可用，不用重启）
├─ watch_ctl.py          控制面板（状态 / 启停 / 开机自启 / 手跑一次）
├─ volume_ctl.py         查看/设置目标设备在 Windows 里的总音量
├─ headphone_watch.py    可选：常驻监听「耳机接入」（仅在耳机经常插拔时有用）
├─ start_watch.bat       启动那个可选监听器（双击可用）
├─ stop_watch.bat        停止那个可选监听器（双击可用）
├─ device_state_probe.py 耳机状态探针（全量监听音频端点，排查触发条件用）
├─ probe_headphone.bat   运行上面的探针（双击可用）
├─ device_probe.py       列出全部输出设备（sounddevice + SAPI 两层）
├─ audio_check.py        三层音频诊断：蜂鸣 / 波形 / 语音
├─ audio_diag.py         SAPI 输出设备诊断
├─ mic_probe.py          麦克风电平扫描
├─ stt_test.py           语音识别闭环测试
├─ config.json           麦克风、唤醒词、灵敏度、输出设备、铃声音量、穿衣播报
├─ tasks.json            任务清单（daily=每天, due=指定日期）
├─ reminders.json        定时提醒队列（自动维护）
├─ notify.json           外部通知收件箱（我写，它念）
├─ questions.md          语音里没听懂的记录
├─ assistant.log         运行日志
├─ tts.log               每次播报/响铃实际用的输出设备
├─ dressing_brief.log    穿衣播报每次的执行流水
├─ dressing_boot.log     穿衣播报的等待/执行流水
├─ dressing_watch.log    耳机监听的轮询/触发记录（用可选监听器时才有）
├─ device_state_probe.log 耳机状态探针的结果（排查用）
├─ dressing_watch.heartbeat / .pid   监听器心跳与进程号（自动维护）
├─ assistant.heartbeat   心跳（自动维护，供 notify.py --status 判断助手死活）
└─ models/               本地识别模型（base，138MB）
```

项目外的文件（WorkBuddy 自动响铃用）：

```
~/.workbuddy/settings.json                       hooks.Stop + hooks.PreToolUse 配置
~/.workbuddy/hooks/wb-chime.py                   hook 转发脚本（收参数指定音色）
~/.workbuddy/hooks/wb-chime.log                  hook 执行日志
~/.workbuddy/settings.json.bak-20260918          改前的配置备份
~/.workbuddy/hooks/wb-done-chime.py.bak          旧版单音脚本（已被 wb-chime.py 取代）
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\
  └─ 小助-耳机穿衣播报.bat                        开机自启：拉起 dressing_boot.py
     （它在内部等 WorkBuddy 起来；关掉用 watch_ctl.py autostart off，或直接删掉这个文件）
```

---

## 硬件现状（重要）

| 设备 | 状态 |
|---|---|
| 麦克风阵列 (Realtek) | **可用**，助手当前用的就是它 |
| **耳机 (Realtek(R) Audio)** | **播报输出**，已由 `output_device` 锁定 |
| HG9086WS（外接设备） | **静音**（-96.7 dBFS），等于没在工作 |
| 扬声器 (Realtek) | 可用，但助手**不往这里出声** |

SAPI 侧可选输出目标（2026-09-18 实测，共 5 个）：

```
[0] 耳机 (Realtek(R) Audio)          <- 当前锁定
[1] 耳机 (HG9086WS)
[2] N50PRO V (NVIDIA High Definition Audio)
[3] 扬声器 (网易虚拟音频设备)
[4] 扬声器 (Realtek(R) Audio)
```

> ⚠️ **索引会变，所以只按名字匹配，绝不写死索引。**
> 实测 2026-09-18：同一个「耳机 (Realtek(R) Audio)」在 sounddevice 的 MME 列表里
> 20:24 是 `[5]`，21:03 就变成了 `[9]`（Windows 重新枚举过设备）。
> 代码里全靠名字模糊匹配（全名 / `耳机` / `Realtek` 都能中），所以位置变动无影响。
> 同理，**系统默认输出设备是什么都无所谓** —— 播报和铃声只认 `output_device` 这个名字。

要启用 HG9086WS 麦克风：`设置 → 系统 → 声音 → 输入`，检查是不是被禁用了或驱动没装。

---

## 排障

**日志显示播报了，但听不到声音** → 跑 `audio_check.py` 分层定位：
- 三层都听到 → 音频通道正常
- 只有蜂鸣听到 → 波形播放和语音合成失败
- 三层都没听到 → 音频输出被静默（换正常窗口启动，别用后台方式）

**声音跑到外放/别处去了** → 先看 `tts.log` 最后一行：
- 写着「命中: 耳机 (Realtek(R) Audio)」→ 设备定向正常，去查耳机电量/插头
- 写着「未匹配到…已退回系统默认」→ 设备名写错了或设备被拔了，
  跑 `device_probe.py` 拿准确名字，改 `config.json` 的 `output_device`

**WorkBuddy 不响铃（办完活 / 提问时）** → 按顺序查三处（从后往前排）：
1. `notify.py --status` —— 助手在不在跑（不在跑也能响，但响铃走的是当场放那条路）
2. `~/.workbuddy/hooks/wb-chime.log` —— hook 到底有没有被执行、**用的是哪个音色**
   （`ok ask（PreToolUse/AskUserQuestion）` / `ok done（Stop）`）
3. 日志里没有新行 → hook 没被触发。先确认 `~/.workbuddy/settings.json` 里
   `hooks.Stop` / `hooks.PreToolUse` 还在、JSON 合法；
   再确认 `~/.workbuddy/hooks/wb-chime.py` 还在。
   实在不行就退回手动：我在任务末尾调 `notify.py --chime "..."`

**问我的时候没响，但办完活响了** → 检查 `wb-chime.log` 里有没有 `ok ask`：
- 有 → hook 触发了，问题在铃声（看 `tts.log` 有没有对应 `[chime] ask`）
- 没有 → matcher 没匹配上。`PreToolUse` 的 `matcher` 是**正则**（区分大小写），
  当前是 `AskUserQuestion|ExitPlanMode`

**两种铃声分不清** → `done` 是上行三音（0.58s，较高），`ask` 是上行两音（0.47s，较低）。
想换音色改 `chime.py` 的 `CHIMES`，但**新音色名要同步加到 `chime_kinds.py`**，
否则 `assert` 会当场报错（这是故意的，防止两边清单漂移）。

**响铃太频繁/太吵** → 改 `config.json` 的 `chime_volume`；要只保留一种，
把 `~/.workbuddy/settings.json` 里对应的那个事件删掉即可（备份见 `.bak-20260918`）。

**叫不醒它** → 看 `assistant.log` 里 `[听到]` 后面的内容，按实际误识别补规则；
或调低 `config.json` 里的 `min_threshold`。

**一直回「我记下了」** → 旧版本的问题，已修复。重启助手即生效。

---

## 配置

`config.json`（**从 `config.example.json` 复制而来，本身不入库**）：

| 键 | 说明 |
|---|---|
| `mic_device` | 麦克风设备号，`null` = 按名称自动找 |
| **`output_device`** | **播报只从这个设备出声**（模糊匹配，全名/简写都行）。留空=跟随系统默认 |
| **`chime_volume`** | **铃声音量**（0.0~1.0，默认 0.9），与播报音量分开调 |
| `wake_words` | 唤醒词数组 |
| `energy_margin` | 说话触发阈值倍数，环境嘈杂就调大 |
| `min_threshold` / `max_threshold` | 阈值上下限，防止噪声底估歪 |
| `silence_sec` | 静音多久算说完了 |
| `followup_sec` | 唤醒后免唤醒窗口（默认 10 秒） |
| `rate` | 语速，185 正常偏快 |
| `hotwords` | 喂给识别模型的热词提示 |
| `dressing_brief.exe` | 桌面上「穿衣建议.exe」的路径，**支持 `~`** |
| `dressing_brief.city` | 天气城市，默认临沂 |
| `dressing_brief.detail` | `full` 全念 / `brief` 只念温度和搭配 |
| `dressing_boot.trigger` | `workbuddy`=等 WorkBuddy 起来再播 / `boot`=登录后直接播 |

改完重启助手生效。

> ⚠️ **音量有两层，先查系统层再改代码。** `volume` / `chime_volume` 是软件层；
> 真正决定响不响的是 **Windows 里那只设备的音量滑块**（实测只有 12% 时怎么调代码都没用）。
> 用 `python volume_ctl.py` 看，`python volume_ctl.py 70` 设成 70%。

---

## 环境与依赖

依赖清单在 `requirements.txt`，装在项目内 `.venv`，不污染系统环境：

| 包 | 干什么用 |
|---|---|
| `faster-whisper` | **本地**语音识别，全程离线、不上传 |
| `sounddevice` | 麦克风采集 |
| `pyttsx3` + `pywin32` | Windows 自带 SAPI 语音合成 |
| `pycaw` + `comtypes` | 读/写 Windows 系统音量（`volume_ctl.py`） |
| `pypinyin` | 唤醒词拼音模糊匹配 |
| `zhconv` | 繁简转换（whisper 常输出繁体） |
| `numpy` | 音频计算与铃声合成 |

**模型**：`models/faster-whisper-base/`（约 140MB）不入库 —— 首次运行
`assistant.py` 检测到缺失会**自动下载**。想换更大的模型改 `config.json` 的
`model`（`small` / `medium`），它会自动下到 `models/faster-whisper-<名字>/`。

**天气数据**：来自 `wttr.in`（免费、免 Key），只用标准库 `urllib` 请求，没有额外依赖。

---

## 许可

代码以 **MIT** 许可发布。`dressing_core.py` 是
[dressing-advice](https://github.com/xiaoming130/dressing-advice)（MIT）的镜像副本，
用于保证「念出来的话」和「穿衣窗口显示的字」同源一致；
穿衣规则与天气抓取的著作权归上游。
