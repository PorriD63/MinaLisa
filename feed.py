#!/usr/bin/env python3
"""Mina & Lisa 飲食紀錄工具。

用法：
  python3 feed.py add <貓> <克數> [--time HH:MM] [--date YYYY-MM-DD] [--note 備註]
      <貓> 可以是 Mina、Lisa，或 both（兩隻共吃的「總」克數，平分成兩筆）
  python3 feed.py weight <貓> <公斤> [--date YYYY-MM-DD]
  python3 feed.py undo [筆數]   刪除最後 N 筆餵食（預設 1）
  python3 feed.py today         顯示今天進度
  python3 feed.py render        重新產生 飲食紀錄.md 與 README.md

每次 add / weight / undo 之後都會自動重新產生 飲食紀錄.md 與 README.md。
"""
import argparse
import calendar
import csv
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")  # 一律用台灣時間判斷「今天」與現在時刻

# ===== 設定（需要調整時改這裡）=====
FOOD_NAME = "皇家 K36 幼貓乾糧"
FOOD_KCAL_PER_KG = 4083   # 代謝能；若包裝上的數字不同，改成包裝的
MAIN_FOOD = "K36"
FOODS = {
    # 代號: (名稱, kcal/kg)。add 時用 --food 代號；沒寫就是 K36
    "K36": (FOOD_NAME, FOOD_KCAL_PER_KG),
    "肉泥": ("汪喵星球 純肉泥", 860),    # 包裝標示 5.16 kcal / 6 g
}
ADULT_WEIGHT_KG = 5.5     # 長大後的預估體重，只用在幼貓成長公式（不是現在的體重）
CATS = {
    # factor：建議量的調整係數。結紮後或獸醫建議增減時再改，例如 0.9
    "Mina": {"birthday": date(2026, 6, 7), "factor": 1.0},
    "Lisa": {"birthday": date(2026, 6, 7), "factor": 1.0},
}
HISTORY_DAYS = 14
# ==================================

BASE = Path(__file__).resolve().parent
FEED_CSV = BASE / "data" / "feedings.csv"
WEIGHT_CSV = BASE / "data" / "weights.csv"
REPORT = BASE / "飲食紀錄.md"
README = BASE / "README.md"
CHART_DAYS = 7
CHART_COLORS = {"Mina": ("#3b82f6", "🟦"), "Lisa": ("#f97316", "🟧")}  # 折線圖每隻貓的顏色
TARGET_COLOR = "#9ca3af"
FEED_HEADER = ["日期", "時間", "貓", "克數", "食物", "備註"]
WEIGHT_HEADER = ["日期", "貓", "體重kg"]
WEEKDAYS = "一二三四五六日"


# ---------- 資料讀寫 ----------

def read_rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_rows(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def append_rows(path, header, rows):
    write_rows(path, header, read_rows(path) + rows)


def load():
    feeds = []
    for r in read_rows(FEED_CSV):
        food = r.get("食物") or MAIN_FOOD
        grams = float(r["克數"])
        feeds.append({**r, "日期": date.fromisoformat(r["日期"]), "克數": grams, "食物": food,
                      "kcal": grams * FOODS[food][1] / 1000})
    weights = [{"日期": date.fromisoformat(r["日期"]), "貓": r["貓"], "kg": float(r["體重kg"])}
               for r in read_rows(WEIGHT_CSV)]
    return feeds, weights


# ---------- 計算 ----------

def kcal(grams):
    """K36 克數 → kcal（其他食物的熱量在 load() 時就算好）。"""
    return grams * FOOD_KCAL_PER_KG / 1000


def grams_for(kcal_value):
    return kcal_value * 1000 / FOOD_KCAL_PER_KG


def weight_on(cat, d, weights):
    """當天（含）之前最近一次的體重；都在之後就用最早那筆。"""
    rows = sorted((w for w in weights if w["貓"] == cat), key=lambda w: w["日期"])
    if not rows:
        return None
    before = [w for w in rows if w["日期"] <= d]
    return before[-1] if before else rows[0]


def target_kcal(cat, d, weights):
    """NRC 2006 幼貓成長能量需求：100 × BW^0.67 × 6.7 × (e^(−0.189p) − 0.66)，p = 體重/成貓體重。"""
    w = weight_on(cat, d, weights)
    if not w:
        return None
    kg = w["kg"]
    p = min(kg / ADULT_WEIGHT_KG, 1.0)
    return 100 * kg ** 0.67 * 6.7 * (math.exp(-0.189 * p) - 0.66) * CATS[cat]["factor"]


def day_feeds(cat, d, feeds):
    return [f for f in feeds if f["貓"] == cat and f["日期"] == d]


def eaten_kcal(cat, d, feeds):
    return sum(f["kcal"] for f in day_feeds(cat, d, feeds))


def grams_text(rows):
    """「66.4 g + 肉泥 3 g」：K36 寫克數，其他食物加上名稱。"""
    by_food = {}
    for f in rows:
        by_food[f["食物"]] = by_food.get(f["食物"], 0) + f["克數"]
    parts = [f"{g(by_food.pop(MAIN_FOOD))} g"] if MAIN_FOOD in by_food else []
    parts += [f"{food} {g(x)} g" for food, x in by_food.items()]
    return " + ".join(parts) or "0 g"


def remaining(target, kcal_eaten):
    """離每日建議還差多少（換算成 K36 克數）：差 5 g 以內或超過不到 10% 都算達標。"""
    rest = grams_for(target - kcal_eaten)
    if kcal_eaten > target * 1.1:
        return f"已超過約 {round(-rest)} g"
    if rest <= 5:
        return "已達標 🎉"
    return f"還可吃約 {round(rest)} g"


def age(birthday, d):
    months = (d.year - birthday.year) * 12 + d.month - birthday.month
    if d.day < birthday.day:
        months -= 1
    y, m = divmod(birthday.month - 1 + months, 12)
    anchor_day = min(birthday.day, calendar.monthrange(birthday.year + y, m + 1)[1])
    anchor = date(birthday.year + y, m + 1, anchor_day)
    return f"{months} 個月 {(d - anchor).days} 天"


# ---------- 格式 ----------

def g(x):
    return f"{round(x, 1):g}"


def md(d):
    return f"{d.month}/{d.day}（{WEEKDAYS[d.weekday()]}）"


def bar(pct):
    n = min(10, round(pct / 10))
    return ("🟧" if pct > 110 else "🟩") * n + "⬜" * (10 - n)


def verdict(pct):
    if pct < 90:
        return "🔽 偏少"
    if pct > 110:
        return "🔼 偏多"
    return "✅"


# ---------- 產生報表 ----------

def header_lines(note):
    return [
        f"# 🐾 {' & '.join(CATS)} 飲食紀錄",
        "",
        f"> 最後更新：{datetime.now(TZ):%Y-%m-%d %H:%M}　·　"
        + "　".join(f"{name}（1 g ≈ {k / 1000:.2f} kcal）" for name, k in FOODS.values()),
        f"> {note}",
        "",
    ]


def chart_lines(feeds, weights, today, days=CHART_DAYS):
    """最近 N 天（不含今天）每天吃了建議量的幾 %，用 GitHub 會直接畫出來的 Mermaid 折線圖。"""
    cats = list(CATS)
    end = today - timedelta(days=1)
    first = min((f["日期"] for f in feeds), default=today)
    dates = [end - timedelta(days=i) for i in range(days - 1, -1, -1)]
    dates = [d for d in dates if d >= first]
    if not dates:
        return []
    series = {}
    for c in cats:
        vals = []
        for d in dates:
            t = target_kcal(c, d, weights)
            vals.append(round(eaten_kcal(c, d, feeds) / t * 100) if t else 0)
        series[c] = vals
    top = max(120, math.ceil(max(max(v) for v in series.values()) / 10) * 10 + 10)
    palette = ", ".join([CHART_COLORS.get(c, ("#6b7280", ""))[0] for c in cats] + [TARGET_COLOR])
    legend = "　".join(f"{CHART_COLORS.get(c, ('', '⬛'))[1]} {c}" for c in cats) + "　⬜ 建議量 100%"
    lines = [
        f"## 📉 最近 {len(dates)} 天：吃了建議量的幾 %",
        "",
        legend,
        "",
        "```mermaid",
        f'%%{{init: {{"themeVariables": {{"xyChart": {{"plotColorPalette": "{palette}"}}}}}}}}%%',
        "xychart-beta",
        '    x-axis [' + ", ".join(f'"{d.month}/{d.day}"' for d in dates) + "]",
        f'    y-axis "% 建議量" 0 --> {top}',
    ]
    lines += [f"    line [{', '.join(str(v) for v in series[c])}]" for c in cats]
    lines += [f"    line [{', '.join('100' for _ in dates)}]", "```", ""]
    lines += ["| 日期 | " + " | ".join(cats) + " |", "|---|" + "--:|" * len(cats)]
    for d in reversed(dates):
        cells = []
        for c in cats:
            rows = day_feeds(c, d, feeds)
            t = target_kcal(c, d, weights)
            e = eaten_kcal(c, d, feeds)
            cells.append(f"{grams_text(rows)} · {round(e)} kcal · {round(e / t * 100) if t else 0}%"
                         if rows else "—")
        lines.append(f"| {md(d)} | " + " | ".join(cells) + " |")
    return lines + [""]


def today_lines(feeds, weights, today):
    cats = list(CATS)
    lines = [
        f"## 📅 今天 {today.year}/{md(today)}",
        "",
        "| | " + " | ".join(cats) + " |",
        "|---|" + ":-:|" * len(cats),
    ]

    stats = {}
    for c in cats:
        t = target_kcal(c, today, weights)
        e = eaten_kcal(c, today, feeds)
        stats[c] = (t, e, e / t * 100 if t else None)

    def row(label, fn):
        lines.append(f"| {label} | " + " | ".join(fn(c) for c in cats) + " |")

    def weight_cell(c):
        w = weight_on(c, today, weights)
        return f"{g(w['kg'])} kg（{w['日期'].month}/{w['日期'].day} 量）" if w else "尚未記錄"

    row("年齡", lambda c: age(CATS[c]["birthday"], today))
    row("體重", weight_cell)
    row("**每日建議**", lambda c: f"**{round(stats[c][0])} kcal ≈ {round(grams_for(stats[c][0]))} g**"
        if stats[c][0] else "需要先記錄體重")
    row("今天已吃", lambda c: f"{grams_text(day_feeds(c, today, feeds))} · {round(stats[c][1])} kcal")
    row("進度", lambda c: f"{bar(stats[c][2])} {round(stats[c][2])}%" if stats[c][2] is not None else "—")
    row("狀態", lambda c: f"**{remaining(stats[c][0], stats[c][1])}**" if stats[c][0] else "—")

    # 今天每一餐
    todays = sorted((f for f in feeds if f["日期"] == today), key=lambda f: f["時間"] or "99:99")
    lines += ["", "**今天每一餐**", ""]
    if todays:
        lines += ["| 時間 | " + " | ".join(cats) + " | 備註 |", "|---|" + "--:|" * len(cats) + "---|"]
        by_time = {}
        for f in todays:
            slot = by_time.setdefault(f["時間"], {"notes": []})
            slot.setdefault(f["貓"], []).append(f)
            if f["備註"] and f["備註"] not in slot["notes"]:
                slot["notes"].append(f["備註"])
        for t, slot in by_time.items():
            cells = [grams_text(slot[c]) if c in slot else "—" for c in cats]
            lines.append(f"| {t or '—'} | " + " | ".join(cells) + f" | {'、'.join(slot['notes'])} |")
    else:
        lines.append("_今天還沒有紀錄_")
    return lines + [""]


def render(feeds, weights, today):
    cats = list(CATS)
    lines = header_lines("這份檔案是自動產生的，不用手動改。要記錄餵食，直接跟 Claude 說「Mina 吃了 20 克」就好。")
    lines += today_lines(feeds, weights, today)
    lines += chart_lines(feeds, weights, today)

    # 最近幾天
    start = min([f["日期"] for f in feeds] + [today])
    start = max(start, today - timedelta(days=HISTORY_DAYS - 1))
    lines += [f"## 📈 最近 {HISTORY_DAYS} 天", "",
              "| 日期 | " + " | ".join(cats) + " |", "|---|" + "---|" * len(cats)]
    d = today
    while d >= start:
        cells = []
        for c in cats:
            rows = day_feeds(c, d, feeds)
            t = target_kcal(c, d, weights)
            if not rows:
                cells.append("—")
                continue
            e = eaten_kcal(c, d, feeds)
            pct = e / t * 100 if t else 0
            mark = "進行中" if d == today else verdict(pct)
            cells.append(f"{grams_text(rows)} · {round(e)} kcal · {round(pct)}% {mark}")
        lines.append(f"| {md(d)} | " + " | ".join(cells) + " |")
        d -= timedelta(days=1)
    lines += ["", "✅ 達成 90–110%　🔽 低於 90%　🔼 超過 110%　— 沒有紀錄"]

    # 體重
    lines += ["", "## ⚖️ 體重", "", "| 日期 | " + " | ".join(cats) + " |", "|---|" + ":-:|" * len(cats)]
    for wd in sorted({w["日期"] for w in weights}, reverse=True):
        cells = []
        for c in cats:
            hit = [w for w in weights if w["日期"] == wd and w["貓"] == c]
            cells.append(f"{g(hit[-1]['kg'])} kg" if hit else "—")
        lines.append(f"| {wd.year}/{md(wd)} | " + " | ".join(cells) + " |")
    lines += ["", "建議每週同一時間量一次（例如週日早上餵食前），建議熱量會跟著體重自動更新。"]

    # 說明
    lines += [
        "",
        "## 📖 建議熱量怎麼算",
        "",
        "- **公式**：NRC 2006 幼貓成長需求　每日 kcal = 100 × 體重<sup>0.67</sup> × 6.7 × (e<sup>−0.189 × 體重 ÷ 成貓體重</sup> − 0.66)",
        f"- **長大後的預估體重**：{g(ADULT_WEIGHT_KG)} kg（布偶母貓成年約 4.5–6.8 kg）。這**不是現在的體重**，公式用它判斷「還要長多少」：離成年體重越遠，每公斤需要的熱量越高。",
        f"- **K36 熱量**：{FOOD_KCAL_PER_KG:,} kcal/kg，每克約 {kcal(1):.2f} kcal（皇家 Kitten 乾糧規格；若包裝上的「代謝能」不同，以包裝為準）",
        f"- **肉泥熱量**：{FOODS['肉泥'][0]} 包裝標示 5.16 kcal / 6 g，每克約 {FOODS['肉泥'][1] / 1000:.2f} kcal；「還差多少 g」都換算成 K36 的克數。",
        "- **皇家包裝餵食表（只餵乾糧）**：1.3–2 kg、3–4 個月 61–67 g；2.3–2.9 kg、5–6 個月 67–70 g；3.1–4 kg、7–12 個月 51–65 g",
        "- 布偶貓體型大、發育期長，所以建議量會比包裝表略高。真正的標準是：**每週體重穩定上升、摸得到肋骨但看不到**。",
        "- 結紮後熱量需求會下降，記得跟獸醫討論新的份量；K36 適用到 12 個月大。",
        "- 以上是一般參考值，不能取代獸醫的建議。",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    readme = header_lines(f"自動產生，不用手動改。完整紀錄（最近 {HISTORY_DAYS} 天、體重、建議量算法）見 [飲食紀錄.md](飲食紀錄.md)。")
    readme += today_lines(feeds, weights, today)
    readme += chart_lines(feeds, weights, today)
    README.write_text("\n".join(readme), encoding="utf-8")


def today_summary(feeds, weights, today):
    out = [f"{today.year}/{md(today)} 今天進度："]
    for c in CATS:
        t = target_kcal(c, today, weights)
        e = eaten_kcal(c, today, feeds)
        text = grams_text(day_feeds(c, today, feeds))
        if t is None:
            out.append(f"  {c}  {text} = {round(e)} kcal（還沒有體重，無法算建議量）")
            continue
        out.append(f"  {c}  {text} = {round(e)} kcal / 建議 {round(t)} kcal"
                   f"（{round(e / t * 100)}%）→ {remaining(t, e)}")
    return "\n".join(out)


# ---------- 指令 ----------

def resolve_cat(name, allow_both=False):
    for c in CATS:
        if c.lower() == name.lower():
            return c
    if allow_both and name.lower() in ("both", "兩隻", "all"):
        return "both"
    sys.exit(f"找不到貓「{name}」，可用：{', '.join(CATS)}" + ("、both" if allow_both else ""))


def main():
    ap = argparse.ArgumentParser(description="Mina & Lisa 飲食紀錄")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="記錄一次餵食")
    a.add_argument("cat")
    a.add_argument("grams", type=float)
    a.add_argument("--date")
    a.add_argument("--time")
    a.add_argument("--note", default="")
    a.add_argument("--food", default=MAIN_FOOD, choices=list(FOODS))
    w = sub.add_parser("weight", help="記錄體重")
    w.add_argument("cat")
    w.add_argument("kg", type=float)
    w.add_argument("--date")
    u = sub.add_parser("undo", help="刪除最後 N 筆餵食")
    u.add_argument("n", nargs="?", type=int, default=1)
    sub.add_parser("today", help="顯示今天進度")
    sub.add_parser("render", help="重新產生 飲食紀錄.md")
    args = ap.parse_args()

    now = datetime.now(TZ)
    today = now.date()

    if args.cmd == "add":
        cat = resolve_cat(args.cat, allow_both=True)
        d = date.fromisoformat(args.date) if args.date else today
        t = args.time or (f"{now:%H:%M}" if d == today else "")
        food = "" if args.food == MAIN_FOOD else args.food
        if cat == "both":
            each, note = args.grams / 2, "、".join(filter(None, [f"兩隻共 {g(args.grams)} g 平分", args.note]))
            rows = [{"日期": d, "時間": t, "貓": c, "克數": g(each), "食物": food, "備註": note} for c in CATS]
        else:
            rows = [{"日期": d, "時間": t, "貓": cat, "克數": g(args.grams), "食物": food, "備註": args.note}]
        append_rows(FEED_CSV, FEED_HEADER, rows)
        k = FOODS[args.food][1] / 1000
        for r in rows:
            print(f"已記錄：{r['貓']} {args.food} {r['克數']} g（{round(float(r['克數']) * k)} kcal）"
                  f"{d.month}/{d.day} {t}".rstrip())
    elif args.cmd == "weight":
        cat = resolve_cat(args.cat)
        d = date.fromisoformat(args.date) if args.date else today
        rows = [r for r in read_rows(WEIGHT_CSV) if not (r["日期"] == d.isoformat() and r["貓"] == cat)]
        rows.append({"日期": d.isoformat(), "貓": cat, "體重kg": g(args.kg)})
        rows.sort(key=lambda r: (r["日期"], r["貓"]))
        write_rows(WEIGHT_CSV, WEIGHT_HEADER, rows)
        print(f"已記錄體重：{cat} {g(args.kg)} kg（{d.month}/{d.day}）")
    elif args.cmd == "undo":
        rows = read_rows(FEED_CSV)
        if not rows:
            sys.exit("沒有餵食紀錄可以刪除")
        n = min(args.n, len(rows))
        for r in rows[-n:]:
            print(f"已刪除：{r['日期']} {r['時間']} {r['貓']} {r.get('食物') or MAIN_FOOD} {r['克數']} g {r['備註']}".rstrip())
        write_rows(FEED_CSV, FEED_HEADER, rows[:-n])

    feeds, weights = load()
    render(feeds, weights, today)
    if args.cmd != "render":
        print(today_summary(feeds, weights, today))


if __name__ == "__main__":
    main()
