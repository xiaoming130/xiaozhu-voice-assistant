# -*- coding: utf-8 -*-
"""watch_ctl.py —— 耳机监听器的开关面板。

    python watch_ctl.py status          # 看现在跑没跑、设备在不在、心跳是否新鲜
    python watch_ctl.py start           # 启动监听（后台常驻，已在跑则不动）
    python watch_ctl.py stop            # 停掉监听
    python watch_ctl.py restart         # 重启
    python watch_ctl.py boot            # 【推荐】立刻按「开机流程」播一次（含等待）
    python watch_ctl.py autostart on            # 开机自启 = 登录后播一次（默认）
    python watch_ctl.py autostart on watch      # 开机自启 = 常驻监听耳机接入
    python watch_ctl.py autostart off           # 取消开机自启

两种触发模式的区别（重要）：
    boot  —— 登录后播一次，跑完即退，**没有常驻进程**。耳机一直插着时用这个。
    watch —— 常驻监听「耳机接入」边沿。只在耳机**经常插拔**时才有意义；
             若耳机常驻，设备从开机起就在场，边沿永不发生，等于不会触发。

为什么要这个：headphone_watch.py 是无窗口常驻进程，出问题没法「点一下关掉」。
这里用 PID 文件精确找到它，避免误杀别的 python 进程。

自启走【启动文件夹】而不是注册表 Run 键 —— 实测这台机器上 Run 键有守护程序，
写进去会被静默回滚（对照键 HKCU\\Software\\XiaozhuProbe 能留住，Run 键留不住），
所以改用启动文件夹里的一个 .bat（GBK 编码，cmd.exe 在中文 Windows 按 936 读）。
"""

import os
import sys
import json
import time
import ctypes
import subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(BASE_DIR, "dressing_watch.pid")
HEARTBEAT = os.path.join(BASE_DIR, "dressing_watch.heartbeat")
LOG_FILE = os.path.join(BASE_DIR, "dressing_watch.log")

AUTOSTART_BAT = "小助-耳机穿衣播报.bat"
LEGACY_REG_NAME = "XiaozhuHeadphoneWatch"   # 早先试过注册表，留着以便清理
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

CREATE_DETACHED = 0x00000008
CREATE_NEW_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def startup_dir():
    return os.path.join(os.environ.get("APPDATA", ""),
                        "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def startup_bat_path():
    return os.path.join(startup_dir(), AUTOSTART_BAT)


# 自启有两种模式：
#   boot  = 开机（登录）后播一次，跑完即退，无常驻进程  <- 默认，耳机常插时用这个
#   watch = 常驻监听「耳机接入」，插上才播            <- 耳机经常插拔时才有意义
AUTOSTART_MODES = {
    "boot": ("dressing_boot.py", "等 WorkBuddy 起来后播一次（无常驻进程）"),
    "watch": ("headphone_watch.py", "常驻监听耳机接入"),
}


def _bat_for(mode):
    script, desc = AUTOSTART_MODES[mode]
    pyw = os.path.normpath(os.path.join(BASE_DIR, ".venv", "Scripts", "pythonw.exe"))
    target = os.path.normpath(os.path.join(BASE_DIR, script))
    content = ("@echo off\r\n"
               f"rem Xiaozhu dressing briefing - mode={mode} ({desc})\r\n"
               f'start "" "{pyw}" "{target}"\r\n'
               "exit\r\n")
    return content, target


def current_mode():
    """看启动文件夹里那个 bat 指的是哪个模式。"""
    p = startup_bat_path()
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="gbk", errors="replace") as f:
            txt = f.read()
        for m, (script, _) in AUTOSTART_MODES.items():
            if script in txt:
                return m
    except Exception:
        pass
    return "?"


def autostart_state():
    """返回 (是否已启用, 说明文字)。启动文件夹 .bat 为准。"""
    p = startup_bat_path()
    if not os.path.exists(p):
        return False, ""
    m = current_mode()
    if m in AUTOSTART_MODES:
        return True, f"{p}  [模式={m} · {AUTOSTART_MODES[m][1]}]"
    return True, p


def do_autostart(on, mode="boot"):
    bat = startup_bat_path()
    if on:
        if mode not in AUTOSTART_MODES:
            print(f"未知模式 {mode!r}，可选: {', '.join(AUTOSTART_MODES)}")
            return 2
        content, target = _bat_for(mode)
        if not os.path.exists(target):
            print(f"找不到 {target}，无法配置自启。")
            return 1
        try:
            os.makedirs(startup_dir(), exist_ok=True)
            with open(bat, "w", encoding="gbk", newline="") as f:
                f.write(content)
        except Exception as e:
            print(f"写入启动器失败: {type(e).__name__} {e}")
            return 1
        print(f"已开启开机自启（模式={mode}）:")
        print("   ", bat)
        print("    ->", target)
        # 顺手清掉早先可能残留在注册表里的同名项
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
            try:
                winreg.DeleteValue(k, LEGACY_REG_NAME)
            except FileNotFoundError:
                pass
            winreg.CloseKey(k)
        except Exception:
            pass
        return 0

    # 关闭：删启动器 + 清注册表残留
    removed = False
    if os.path.exists(bat):
        try:
            os.remove(bat)
            print("已关闭开机自启（已删除启动器）:")
            print("   ", bat)
            removed = True
        except Exception as e:
            print(f"删除启动器失败: {e}")
            return 1
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(k, LEGACY_REG_NAME)
            print("已清理注册表残留项。")
            removed = True
        except FileNotFoundError:
            pass
        winreg.CloseKey(k)
    except Exception:
        pass
    if not removed:
        print("本来就没开启机自启。")
    return 0



def pid_alive(pid):
    try:
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(0x1000, False, int(pid))   # QUERY_LIMITED_INFORMATION
        if h:
            k32.CloseHandle(ctypes.c_void_p(h))
            return True
        return False
    except Exception:
        return False


def read_pid():
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return None


def interpreter():
    pyw = os.path.join(BASE_DIR, ".venv", "Scripts", "pythonw.exe")
    return pyw if os.path.exists(pyw) else sys.executable


def do_start(quiet=False):
    pid = read_pid()
    if pid and pid_alive(pid):
        if not quiet:
            print(f"监听已在运行 (pid={pid})，无需重复启动。")
        return 0
    try:
        p = subprocess.Popen(
            [interpreter(), os.path.join(BASE_DIR, "headphone_watch.py")],
            cwd=BASE_DIR,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=CREATE_DETACHED | CREATE_NEW_GROUP | CREATE_NO_WINDOW,
            close_fds=True,
        )
        time.sleep(2.0)
        newpid = read_pid()
        if not quiet:
            print(f"监听已启动 (pid={newpid or p.pid})。")
        return 0
    except Exception as e:
        print(f"启动失败: {type(e).__name__} {e}")
        return 1


def do_stop(quiet=False):
    pid = read_pid()
    if not pid:
        if not quiet:
            print("没找到 PID 文件，可能本来就没在跑。")
        return 0
    if not pid_alive(pid):
        try:
            os.remove(PID_FILE)
        except Exception:
            pass
        if not quiet:
            print(f"PID 文件里的 {pid} 早已退出，已清理。")
        return 0
    subprocess.run(["taskkill", "/F", "/PID", str(pid), "/T"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=CREATE_NO_WINDOW)
    time.sleep(1.0)
    ok = not pid_alive(pid)
    if ok:
        try:
            os.remove(PID_FILE)
        except Exception:
            pass
    if not quiet:
        print(f"监听已停止 (pid={pid})。" if ok else f"停止失败，{pid} 仍在运行。")
    return 0 if ok else 1


def do_status():
    print("=" * 60)
    print("小助 · 耳机穿衣播报 监听器")
    print("=" * 60)

    # 1) 进程
    pid = read_pid()
    running = bool(pid and pid_alive(pid))
    print(f"  监听进程   : {'运行中  pid=' + str(pid) if running else '未运行'}")

    # 2) 心跳
    if os.path.exists(HEARTBEAT):
        age = time.time() - os.path.getmtime(HEARTBEAT)
        fresh = "正常" if age < 30 else "偏旧(可能卡住)"
        print(f"  最后心跳   : {age:.0f} 秒前  [{fresh}]")
    else:
        print("  最后心跳   : 无")

    # 3) 配置
    try:
        with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        w = cfg.get("headphone_watch", {})
        d = cfg.get("dressing_brief", {})
        b = cfg.get("dressing_boot", {})
        on_off = lambda v: "开" if v else "关"
        print(f"  监听开关   : {on_off(w.get('enabled', True))}"
              f"   （监听器只在『耳机经常插拔』时才有用）")
        print(f"  匹配关键词 : {w.get('must_include')}")
        print(f"  轮询/冷却  : {w.get('poll_sec')}s / {w.get('cooldown_sec')}s")
        print(f"  开局补触发 : {w.get('fire_on_start')}")
        print(f"  开机播报   : {on_off(b.get('enabled', True))}"
              f"   先等 {b.get('delay_sec')}s，网络上限 {b.get('network_timeout_sec')}s")
        trig = (b.get("trigger") or "workbuddy")
        if trig == "workbuddy":
            print(f"  触发条件   : 等 {b.get('wb_image', 'WorkBuddy.exe')} 起来"
                  f"（上限 {b.get('wb_timeout_sec')}s"
                  f"，等不到{'不播' if b.get('wb_required', True) else '照样播'}）")
        else:
            print(f"  触发条件   : trigger={trig}（登录后直接播）")
        print(f"  播报城市   : {d.get('city')}")
        print(f"  是否弹窗   : {on_off(d.get('launch_exe', True))}"
              f"   播完关窗={on_off(d.get('close_window', True))}"
              f"   详略={d.get('detail')}")
        exe = d.get("exe", "")
        print(f"  目标 exe   : {exe}  [{'存在' if os.path.exists(exe) else '找不到!'}]")
    except Exception as e:
        print(f"  配置读取失败: {e}")

    # 4) 实时设备判定
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "hw", os.path.join(BASE_DIR, "headphone_watch.py"))
        hw = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hw)
        _, w = hw.load_cfgs()
        names = hw.list_outputs() or []
        t = hw.match_target(names, w["must_include"])
        print(f"  输出设备数 : {len(names)}")
        print(f"  目标耳机   : {'在场 -> ' + t if t else '不在场'}")
    except Exception as e:
        print(f"  设备探测失败: {e}")

    # 5) 自启项
    on, val = autostart_state()
    print(f"  开机自启   : {'已开启' if on else '未开启'}")
    if on:
        print(f"                {val}")

    print("=" * 60)
    return 0


def do_boot():
    """立刻按「开机流程」跑一次（含等待网络/设备）。前台跑，能看到输出。"""
    py = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
    if not os.path.exists(py):
        py = sys.executable
    print("按开机流程播一次（会先等待网络与设备就绪）…")
    r = subprocess.run([py, os.path.join(BASE_DIR, "dressing_boot.py")],
                       cwd=BASE_DIR)
    return r.returncode


def main():
    args = sys.argv[1:]
    cmd = (args[0] if args else "status").lower()
    if cmd == "start":
        return do_start()
    if cmd == "stop":
        return do_stop()
    if cmd == "restart":
        do_stop(quiet=True)
        return do_start()
    if cmd == "status":
        return do_status()
    if cmd in ("boot", "play"):
        return do_boot()
    if cmd == "autostart":
        sub = (args[1] if len(args) > 1 else "").lower()
        mode = (args[2] if len(args) > 2 else "boot").lower()
        if sub in ("on", "1", "true", "enable"):
            return do_autostart(True, mode)
        if sub in ("off", "0", "false", "disable"):
            return do_autostart(False)
        print("用法: watch_ctl.py autostart on [boot|watch]   /   watch_ctl.py autostart off")
        return 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
