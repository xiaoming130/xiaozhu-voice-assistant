# -*- coding: utf-8 -*-
"""device_state_probe.py —— 探测「耳机通电/断电」在 Windows 里到底有没有可见信号。

背景：
    目标设备「耳机 (Realtek(R) Audio)」无论耳机开不开，都一直出现在设备列表里，
    所以「设备在不在」这个信号没用。要查的是**更细的东西**：

      A. 每个音频端点的状态（Core Audio 层，pycaw 读得到）
             Active      已启用且就绪（能出声）
             Unplugged   已拔出 / 断开
             NotPresent  系统知道它存在，但当前未接入
             Disabled    被禁用
      B. 当前默认输出设备（eConsole / eMultimedia 两种角色）

    本脚本做**全量监听**：不是只盯目标设备，而是把**所有音频端点**的状态快照下来
    整体比对。这样连蓝牙重连、USB 声卡插拔之类的痕迹也不会漏。

用法：
    python device_state_probe.py            # 观察 120 秒
    python device_state_probe.py 180        # 观察 180 秒
    python device_state_probe.py 0          # 一直观察，按 Ctrl+C 停

配合操作（关键，不做这个测不出来）：
    跑起来之后，请**把耳机断电，等十几秒，再通电**。

依赖：pycaw（已装进 .venv）
"""

import os
import re
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "device_state_probe.log")

# 目标关键词：必须全部命中
MUST_INCLUDE = ["耳机", "Realtek"]


def log(msg, echo=True):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if echo:
        print(line, flush=True)


def norm(s):
    return re.sub(r"\s+", "", (s or "").lower())


def matches(name, kws):
    low = norm(name)
    return all(norm(k) in low for k in kws)


def state_name(st):
    return str(st).split(".")[-1] if st is not None else "?"


def snapshot():
    """采一帧全量快照。

    返回 (endpoints_dict, defaults_dict, target_states)
        endpoints_dict : {设备id: "名字|状态"}
        defaults_dict  : {角色: "设备名|状态"}
        target_states  : 命中关键词的设备的状态集合
    """
    from pycaw.utils import AudioUtilities

    eps, tgt = {}, set()
    try:
        for d in AudioUtilities.GetAllDevices():
            name = getattr(d, "FriendlyName", "") or ""
            st = state_name(getattr(d, "state", None))
            eps[getattr(d, "id", str(id(d)))] = f"{name}|{st}"
            if matches(name, MUST_INCLUDE):
                tgt.add(st)
    except Exception as e:
        eps["<err>"] = f"{type(e).__name__}"

    defaults = {}
    try:
        # 直接用 pycaw 封装好的 GetSpeakers()（= 默认渲染设备）。
        # 不要自己调 IMMDeviceEnumerator.GetDefaultAudioEndpoint：comtypes 传
        # EDataFlow/ERole 会抛 ArgumentError，实测踩过，改用这个封装就正常。
        spk = AudioUtilities.GetSpeakers()
        nm = getattr(spk, "FriendlyName", None) or str(spk)
        st = state_name(getattr(spk, "state", None))
        defaults["默认输出设备"] = f"{nm}|{st}"
    except Exception as e:
        defaults["默认输出设备"] = f"<{type(e).__name__}>"

    return eps, defaults, tgt


def fmt(s):
    return "/".join(sorted(s)) if s else "(无)"


def main():
    dur = 120
    if len(sys.argv) > 1:
        try:
            dur = int(sys.argv[1])
        except ValueError:
            pass

    log("=" * 60)
    log(f"耳机状态探针（全量模式）启动  目标关键词={MUST_INCLUDE}  观察 {dur or '∞'} 秒")
    log(">>> 现在请把耳机【断电】，等 15 秒，再【通电】。必须真的做，否则测不出来。")

    prev_eps = prev_def = prev_tgt = None
    changes = 0
    t0 = time.time()
    n = 0

    try:
        while True:
            if dur and time.time() - t0 >= dur:
                break
            n += 1
            eps, defs, tgt = snapshot()

            if prev_eps is None:
                log(f"[基线] 音频端点共 {len(eps)} 个")
                log(f"       目标设备状态 = {fmt(tgt)}")
                for k, v in defs.items():
                    log(f"       {k} = {v}")
            else:
                if tgt != prev_tgt:
                    changes += 1
                    log(f"*** 目标设备状态变化! {fmt(prev_tgt)}  ->  {fmt(tgt)}")

                if defs != prev_def:
                    for k in defs:
                        if defs.get(k) != (prev_def or {}).get(k):
                            changes += 1
                            log(f"*** 默认设备[{k}]变化! "
                                f"{(prev_def or {}).get(k)}  ->  {defs.get(k)}")

                # 全量端点比对：只看出现/消失/状态变化的
                added = set(eps) - set(prev_eps)
                removed = set(prev_eps) - set(eps)
                for k in added:
                    changes += 1
                    log(f"*** 端点出现: {eps[k]}")
                for k in removed:
                    changes += 1
                    log(f"*** 端点消失: {prev_eps[k]}")
                for k in set(eps) & set(prev_eps):
                    if eps[k] != prev_eps[k]:
                        changes += 1
                        log(f"*** 端点状态变化: {prev_eps[k]}  ->  {eps[k]}")

            prev_eps, prev_def, prev_tgt = eps, defs, tgt
            time.sleep(1.0)
    except KeyboardInterrupt:
        log("用户中断")

    log("-" * 60)
    log(f"观察结束：共采样 {n} 次，捕获 {changes} 处变化")
    if changes == 0:
        log("结论：耳机通断电期间，【音频层没有任何可见变化】。")
        log("      => Windows 感知不到耳机的电源开关，无法用它做触发条件。")
    else:
        log("结论：存在可用信号（见上面 *** 行），可以把它写进触发条件。")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
