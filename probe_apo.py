"""probe_apo.py —— 查音频端点（耳机）上挂了哪些音效处理对象(APO)。

思路：Windows 把每个音频端点的 APO（音频处理对象）GUID 写在注册表
  HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\MMDevices\\Audio\\Render\\{端点GUID}\\FxProperties
把这些 GUID 认出来，就知道是哪个厂商的软件在耳机这一路上做处理。

用法： python probe_apo.py
"""
import re
import sys
import winreg

RENDER = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
DEVPROP = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"

# 已知音频增强厂商的 APO / 服务 CLSID 特征（用大写比较）
VENDORS = {
    "NAHIMIC": "Nahimic 音效（MSI 整机预装）",
    "A-Volute": "Nahimic 音效（MSI 整机预装）",
    "DOLBY": "Dolby 音效",
    "DTS": "DTS 音效",
    "WAVES": "Waves MaxxAudio",
    "MAXAUDIO": "Waves MaxxAudio",
    "REALTEK": "Realtek 自家音效",
    "CONEXANT": "Conexant 音效",
    "SOUNDRESEARCH": "Sound Research 音效",
    "CIRRUS": "Cirrus 音效",
    "SST": "Intel Smart Sound",
    "INTEL": "Intel 音效组件",
    "APO": "（通用 APO 关键字）",
}


def enum_keys(subpath, hive=winreg.HKEY_LOCAL_MACHINE):
    out = []
    try:
        with winreg.OpenKey(hive, subpath, 0, winreg.KEY_READ) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumKey(k, i))
                    i += 1
                except OSError:
                    break
    except OSError as e:
        print(f"打不开 {subpath}: {e}")
    return out


def read_values(subpath, hive=winreg.HKEY_LOCAL_MACHINE):
    out = {}
    try:
        with winreg.OpenKey(hive, subpath, 0, winreg.KEY_READ) as k:
            i = 0
            while True:
                try:
                    name, val, _ = winreg.EnumValue(k, i)
                    out[name] = val
                    i += 1
                except OSError:
                    break
    except OSError:
        pass
    return out


PKEY_FRIENDLY = "{a45c254e-df1c-4efd-8020-67d146a850e0},14"
PKEY_DESCDEV = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
PKEY_DEVDESC = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"
PKEY_NOSYSFX = "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},5"


def endpoint_name(guid):
    """友好名优先，其次设备描述。"""
    props = read_values(rf"{DEVPROP}\{guid}\Properties")
    low = {k.lower(): v for k, v in props.items()}
    for key in (PKEY_FRIENDLY, PKEY_DEVDESC, PKEY_DESCDEV):
        v = low.get(key.lower())
        if isinstance(v, str) and v.strip():
            return v.strip()
    for v in props.values():
        if isinstance(v, str) and v and not v.startswith("{"):
            return v
    return "(未知)"


def state_of(guid):
    d = read_values(rf"{DEVPROP}\{guid}")
    raw = d.get("DeviceState")
    if raw is None:
        return None, None
    return raw, raw & 0xF          # 低 4 位才是真正的状态位


def main():
    guids = enum_keys(RENDER)
    if not guids:
        print("读不到端点列表（可能权限不足）")
        return 1

    actives = []
    for g in guids:
        name = endpoint_name(g)
        raw, low = state_of(g)
        if low == 1:
            actives.append((g, name))

    print(f"共 {len(guids)} 个播放端点，其中【在用】{len(actives)} 个：\n")
    for g, name in actives:
        print(f"  ★ {name}")
        print(f"      GUID {g}")
    print()

    if not actives:
        print("没有处于 Active 的端点 —— 插着耳机时再跑一次。")
        return 1

    for g, name in actives:
        print("=" * 62)
        print(f"★ 在用端点：{name}")
        print("=" * 62)
        props = read_values(rf"{RENDER}\{g}\Properties")
        low = {k.lower(): v for k, v in props.items()}
        nosys = low.get(PKEY_NOSYSFX.lower())
        if nosys is not None:
            print(f"  音频增强开关 : {'已关闭 ✗' if int(nosys) == 1 else '★开启中 ✓'}"
                  f"   (Disable_SysFx={nosys})")
        else:
            print("  音频增强开关 : 注册表无此项（按系统默认）")

        fx = read_values(rf"{RENDER}\{g}\FxProperties")
        print(f"  音效处理链   : {len(fx)} 条")
        if not fx:
            print("      → 空的，这一路干净，没挂任何处理")
        else:
            hits = {}
            for k, v in sorted(fx.items()):
                sv = str(v)
                short = k.split(",")[-1] if "," in k else k
                if short in ("10", "11"):
                    print(f"      · {sv[:78]}")
                up = (k + " " + sv).upper()
                for key, label in VENDORS.items():
                    if key in up and key != "APO":
                        hits[label] = hits.get(label, 0) + 1
                        break
            print()
            if hits:
                print("  >>> 挂的第三方音效：")
                for label, n in hits.items():
                    print(f"        {label}  ({n} 条)")
            else:
                print("  >>> 没认出第三方厂商 → 是微软自带的那套")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
