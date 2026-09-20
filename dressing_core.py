# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# 【vendored / 上游镜像】请勿手改本文件，改逻辑请回到上游改再同步。
#   来源 : https://github.com/xiaoming130/dressing-advice
#   文件 : dressing_advice.py (分支 master, 拉取时间 2026-09-19)
#   理由 : 桌面「穿衣建议.exe」由该仓库的 dressing_app.py 打包，两者共用同
#          一套 OUTFITS 穿衣表 / WIND_SCALE_THRESHOLD / fetch_weather(wttr.in)。
#          本助手直接复用这份逻辑，保证「念出来的内容」与「exe 窗口显示的内容」
#          同源一致，不会各说各话。
#   依赖 : 纯标准库（urllib / json），无第三方包。
#   注意 : 上游若更新，重新拉取覆盖本文件即可；本文件仅做镜像，不参与修改。
# ---------------------------------------------------------------------------
"""
26度穿衣法则 - 穿衣建议程序（按温度区间成套搭配）

原理：当日气温 + 衣物保暖度 = 26℃（人体体感舒适温度）
本版不再硬凑数值，而是按温度区间直接给出成套搭配。
联网查询时同时展示：气温/体感、天气、风力风向、紫外线（晒不晒）、湿度。

用法：
    python dressing_advice.py 18          # 手动输入气温
    python dressing_advice.py             # 获取默认城市（临沂）气温（需联网）
    python dressing_advice.py --city 北京 # 指定城市（需联网）
"""

import sys
import json
import urllib.request
import urllib.parse

COMFORT = 26  # 人体舒适温度
DEFAULT_CITY = "临沂"  # 默认城市（双击无参运行时使用）

# 温度区间 → 成套搭配
# (下限, 上限, 搭配, 小贴士)  上限不包含（即 [lo, hi)），首尾用 inf 兜底
OUTFITS = [
    (28, float("inf"), "短袖T恤 + 短裤/短裙", "炎热，注意防晒补水"),
    (24, 28, "短袖T恤 + 薄长裤/薄裙", "体感舒适，早晚可备件薄外套"),
    (20, 24, "短袖T恤 + 薄外套", "或长袖衬衫单穿，早晚微凉套外套"),
    (16, 20, "长袖衬衫/薄卫衣 + 薄外套/风衣", "微凉，注意脖子和手腕保暖"),
    (11, 16, "毛衣/针织衫 + 风衣/薄外套", "偏凉，内搭可加打底"),
    (6, 11, "毛衣 + 棉服/夹克", "冷，建议加围巾"),
    (1, 6, "保暖内衣 + 毛衣 + 棉服/薄羽绒服", "寒冷，注意手脚保暖"),
    (float("-inf"), 1, "保暖内衣 + 厚毛衣 + 厚羽绒服/呢大衣", "严寒，尽量减少户外停留"),
]

# 常见天气英文 → 中文
WEATHER_ZH = {
    "Sunny": "晴", "Clear": "晴", "Partly cloudy": "多云", "Cloudy": "阴",
    "Overcast": "阴", "Mist": "薄雾", "Fog": "雾", "Light rain": "小雨",
    "Moderate rain": "中雨", "Heavy rain": "大雨", "Light drizzle": "毛毛雨",
    "Patchy rain nearby": "局部阵雨", "Light snow": "小雪", "Snow": "雪",
    "Moderate snow": "中雪", "Heavy snow": "大雪",
}

# 16 方位风向 → 中文
WIND_DIR_ZH = {
    "N": "北", "NNE": "东北偏北", "NE": "东北", "ENE": "东北偏东",
    "E": "东", "ESE": "东南偏东", "SE": "东南", "SSE": "东南偏南",
    "S": "南", "SSW": "西南偏南", "SW": "西南", "WSW": "西南偏西",
    "W": "西", "WNW": "西北偏西", "NW": "西北", "NNW": "西北偏北",
}

# 蒲福风级阈值（km/h 上限，依次对应 0~12 级）
WIND_SCALE_THRESHOLD = [1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118]


def pick_outfit(temp: float):
    """根据气温返回对应的成套搭配。"""
    for lo, hi, outfit, tip in OUTFITS:
        if lo <= temp < hi:
            return outfit, tip
    return "短袖T恤", ""


def wind_scale(kmph):
    """风速(km/h) → 蒲福风级 0~12。"""
    for lv, thr in enumerate(WIND_SCALE_THRESHOLD):
        if kmph < thr:
            return lv
    return 12


def uv_desc(uv):
    """紫外线指数 → 晒不晒描述（None 或解析失败返回 --）。"""
    if uv is None:
        return "--"
    if uv <= 2:
        return "不晒"
    if uv <= 5:
        return "有点晒"
    if uv <= 7:
        return "较晒"
    if uv <= 10:
        return "很晒"
    return "极晒"


def build_tips(base_tip, desc, temp, wind_kmph, uv):
    """动态组合小贴士：基础搭配提示 + 雨雪/大风/紫外线提醒。"""
    tips = []
    if base_tip:
        tips.append(base_tip)
    if desc:
        if "雨" in desc:
            tips.append("☔ 有雨，出门记得带伞")
        if "雪" in desc:
            tips.append("❄️ 有雪，注意保暖防滑")
    if wind_kmph is not None and wind_kmph >= 20:
        lv = wind_scale(wind_kmph)
        if temp < 24:
            tips.append(f"💨 风力{lv}级较大，体感比气温更低，注意防风")
    if uv is not None and uv >= 6:
        lv_txt = "强" if uv <= 7 else "很强" if uv <= 10 else "极强"
        tips.append(f"☀️ 紫外线{lv_txt}（UV {uv}），出门注意防晒")
    return "\n".join(tips)


def fetch_weather(city: str = None):
    """通过 wttr.in 获取天气，返回 dict（含气温/体感/天气/风/紫外线/湿度）。"""
    base = "https://wttr.in/"
    target = urllib.parse.quote(city) if city else ""
    url = f"{base}{target}?format=j1"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    c = data["current_condition"][0]
    na = data["nearest_area"][0]

    # 天气描述：优先 wttr.in 自带中文，失败再走英文映射（注意 strip 尾随空格）
    desc = None
    if c.get("lang_zh"):
        desc = c["lang_zh"][0].get("value")
    if not desc and c.get("weatherDesc"):
        raw = c["weatherDesc"][0].get("value", "").strip()
        desc = WEATHER_ZH.get(raw, raw)

    try:
        uv = int(c.get("uvIndex"))
    except (TypeError, ValueError):
        uv = None

    try:
        wind_kmph = int(float(c.get("windspeedKmph") or 0))
    except (TypeError, ValueError):
        wind_kmph = None

    try:
        feels = float(c.get("FeelsLikeC"))
    except (TypeError, ValueError):
        feels = None

    return {
        "temp": float(c["temp_C"]),
        "feels": feels,
        "humidity": c.get("humidity"),
        "desc": desc,
        "area": na["areaName"][0]["value"],
        "region": na["region"][0]["value"],
        "wind_kmph": wind_kmph,
        "wind_dir": c.get("winddir16Point") or "",
        "uv": uv,
    }


def main():
    args = sys.argv[1:]
    temp = None
    city = None

    # 解析参数
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--city" and i + 1 < len(args):
            city = args[i + 1]
            i += 2
        else:
            try:
                temp = float(a)
            except ValueError:
                print(f"无法识别的参数: {a}")
                return
            i += 1

    w = None  # 联网天气数据（手动气温时无）
    if temp is None:
        if city is None:
            city = DEFAULT_CITY
        try:
            w = fetch_weather(city)
            temp = w["temp"]
            loc = f"{w['area']}, {w['region']}" if w["region"] else w["area"]
            print(f"已获取「{city}」实时天气（解析到 {loc}）")
        except Exception as e:
            print(f"获取「{city}」天气失败（{e}）")
            try:
                temp = float(input("请输入当日气温（℃）: "))
            except (ValueError, EOFError):
                print("未获取到有效气温，程序退出。")
                return

    outfit, tip = pick_outfit(temp)
    need = COMFORT - temp

    print(f"\n{'=' * 44}")
    print(f"今日气温: {temp}℃ | 舒适温度: {COMFORT}℃")
    print(f"参考需保暖度: {need:.0f}℃")

    # 联网成功才展示环境信息（手动气温模式跳过）
    if w is not None:
        line = []
        if w["desc"]:
            line.append(f"天气: {w['desc']}")
        if w["feels"] is not None:
            line.append(f"体感: {w['feels']}℃")
        if w["humidity"]:
            line.append(f"湿度: {w['humidity']}%")
        if w["wind_kmph"] is not None:
            dir_zh = WIND_DIR_ZH.get(w["wind_dir"], "")
            prefix = f"{dir_zh}风" if dir_zh else "风"
            line.append(f"{prefix} {wind_scale(w['wind_kmph'])}级 {w['wind_kmph']}km/h")
        uv = w.get("uv")
        if uv is not None:
            line.append(f"紫外线 {uv}·{uv_desc(uv)}")
        print("  " + " | ".join(line))

    print(f"{'=' * 44}")
    print(f"建议搭配: {outfit}")

    # 动态小贴士（含雨伞/防风/防晒提醒）
    w_desc = w["desc"] if w else None
    w_wind = w["wind_kmph"] if w else None
    w_uv = w.get("uv") if w else None
    tips = build_tips(tip, w_desc, temp, w_wind, w_uv)
    if tips:
        for t in tips.split("\n"):
            print(f"小贴士: {t}")
    print(f"{'=' * 44}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
    # 双击运行时避免窗口一闪而过
    try:
        input("\n按回车键退出...")
    except EOFError:
        pass
