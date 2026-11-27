"""
theses.json(등록된 전망)과 tracking/prices.csv(일별 종가)를 읽어
- tracking/charts/<ID>.png  추적 차트
- tracking/status.json       현재 상태·판정
- theses/<ID>.md             전망별 문서
를 만듭니다. README는 scripts/build_readme.py 가 status.json 을 읽어 반영합니다.

사용법
  python scripts/track_theses.py

바스켓 수익률: 기준일 종가에 동일 금액을 넣고 보유했다고 가정한 동일가중 수익률
초과수익: 바스켓 수익률 - 벤치마크(KOSPI) 수익률 (%p)
D+n: 기준일 다음 거래일부터 센 n번째 거래일 (prices.csv에 있는 거래일 기준)
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "theses.json"
PRICES = ROOT / "tracking" / "prices.csv"
CHARTS = ROOT / "tracking" / "charts"
STATUS = ROOT / "tracking" / "status.json"
THESES_DIR = ROOT / "theses"

# 색: 범주형 고정 순서(파랑·주황·청록), 벤치마크는 중립 회색
SERIES = ["#257de0", "#f47230", "#00b894"]
BENCH = "#8a8a8a"
TEXT = "#191919"
TEXT2 = "#666666"
GRID = "#e6e6e6"


def load_prices():
    px = defaultdict(dict)
    with open(PRICES, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            px[r["code"]][r["date"]] = float(r["close"])
    return px


def basket_returns(px, codes, dates, base):
    """기준일 대비 동일가중 바스켓 수익률(%) — 모든 종목 가격이 있는 날짜만"""
    out = {}
    for d in dates:
        if all(d in px[c] for c in codes):
            out[d] = (sum(px[c][d] / px[c][base] for c in codes) / len(codes) - 1) * 100
    return out


def nth_trading_day(dates, base, n):
    after = [d for d in dates if d > base]
    return after[n - 1] if len(after) >= n else None


def fmt(x):
    return f"{x:+.1f}%"


def style(ax, title, unit):
    ax.set_title(title, loc="left", fontsize=10, color=TEXT, pad=8)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color("#bdbdbd")
    ax.tick_params(colors=TEXT2, labelsize=8)
    ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(nbins=6, steps=[1, 2, 5, 10], integer=True))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}{unit}"))
    ax.axhline(0, color="#bdbdbd", linewidth=0.8, zorder=1)


def spread(ys, gap):
    """끝 라벨 위치가 gap보다 가까우면 위아래로 벌림"""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    pos = list(ys)
    for k in range(1, len(order)):
        a, b = order[k - 1], order[k]
        if pos[b] - pos[a] < gap:
            pos[b] = pos[a] + gap
    return pos


def plot(t, series, base, out, unit="%", extra=None):
    """x축은 거래일 순서(주말·휴장일 없음), 눈금은 날짜"""
    days = sorted(set().union(*[set(s) for _, s, _, _ in series]))
    ix = {d: i for i, d in enumerate(days)}
    fig, ax = plt.subplots(figsize=(6.4, 3.2), dpi=150)
    if extra:
        extra(ax)
    ends = []
    for name, ser, color, dashed in series:
        ds = sorted(ser)
        xs, ys = [ix[d] for d in ds], [ser[d] for d in ds]
        ax.plot(xs, ys, color=color, linewidth=2, linestyle="--" if dashed else "-",
                label=name, zorder=3)
        ax.plot(xs[-1], ys[-1], "o", ms=4, color=color, zorder=4)
        ends.append((xs[-1], ys[-1]))
    lo, hi = ax.get_ylim()
    pos = spread([y for _, y in ends], (hi - lo) * 0.07)
    for (x, y), py in zip(ends, pos):
        ax.annotate(f"{y:+.1f}{unit}", (x, y), xytext=(x + 0.15, py), textcoords="data",
                    va="center", fontsize=8, color=TEXT)
    bx = ix[base]
    ax.axvline(bx, color=TEXT2, linewidth=0.8, linestyle=":")
    ax.annotate(f"baseline {base[5:].replace('-', '/')}", (bx, 0), xycoords=("data", "axes fraction"),
                xytext=(-3, 4), textcoords="offset points", ha="right", fontsize=7, color=TEXT2)
    step = max(1, len(days) // 8)
    ax.set_xticks(range(0, len(days), step))
    ax.set_xticklabels([days[i][5:].replace("-", "/") for i in range(0, len(days), step)])
    ax.set_xlim(-0.3, len(days) - 1 + 0.9)
    style(ax, f"{t['id']}  {out['chart_title']}", unit)
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.12), ncol=4, frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(CHARTS / f"{t['id']}.png", facecolor="white")
    plt.close(fig)


def evaluate(t, px):
    if t["type"] == "event":
        res = {"id": t["id"], "title": t["title"], "baseline": t["baseline"],
               "judge_date": t["final_date"], "now": t.get("context", "-"), "chart": None,
               "last": max(px["KOSPI"])}
        o = t.get("outcome")
        res["status"] = "⏳ 결과 대기" if o is None else ("✅ 적중" if o else "❌ 빗나감")
        return res
    if t["type"] == "level_interval":
        return evaluate_level(t, px)
    dates = sorted(px[t["benchmark"]])
    base = t["baseline"]
    last = dates[-1]
    bench = basket_returns(px, [t["benchmark"]], dates, base)
    groups = {g: basket_returns(px, cs, dates, base) for g, cs in t["groups"].items()}
    excess = {g: {d: r[d] - bench[d] for d in r if d in bench} for g, r in groups.items()}
    res = {"id": t["id"], "title": t["title"], "baseline": base, "last": last}

    if t["type"] == "range":
        g = next(iter(groups))
        cur = groups[g][last]
        band = t["band_pct"]
        res["judge_date"] = t["final_date"]
        res["now"] = f"바스켓 {fmt(cur)} (허용 ±{band}%)"
        if last >= t["final_date"]:
            fin = groups[g][max(d for d in groups[g] if d <= t["final_date"])]
            res["status"] = "✅ 적중" if abs(fin) <= band else "❌ 빗나감"
        else:
            res["status"] = "⏳ 진행 중" + (" · 범위 안" if abs(cur) <= band else " · 범위 밖")
        res["chart_title"] = "Semis basket vs. ±10% band"

        def band_fill(ax):
            ax.axhspan(-band, band, color="#eef3fb", zorder=0)
        plot(t, [(g, groups[g], SERIES[0], False), ("KOSPI", bench, BENCH, True)], base, res, extra=band_fill)

    elif t["type"] == "rotation":
        bat, mat = "Large-cap battery", "Cathode materials"
        d1 = nth_trading_day(dates, base, t["stage1_days"])
        d2 = nth_trading_day(dates, base, t["final_days"])
        res["judge_date"] = f"D+{t['stage1_days']} / D+{t['final_days']}"
        ko = {"Robotics": "로봇", "Large-cap battery": "대형 배터리", "Cathode materials": "양극재"}
        res["now"] = " · ".join(f"{ko.get(g, g)} {fmt(excess[g][last])}p" for g in t["groups"])
        if d1 is None:
            res["status"] = f"⏳ 진행 중 (D+{len([d for d in dates if d > base])})"
        else:
            s1 = excess[bat][d1] > 0
            if not s1:
                res["status"] = "❌ 빗나감 (1단계 미충족)"
            elif d2 is None:
                res["status"] = "⏳ 1단계 충족 · 2단계 진행 중"
            else:
                win = [d for d in dates if base < d <= d2]
                pk_b = max(win, key=lambda d: excess[bat][d])
                pk_m = max(win, key=lambda d: excess[mat][d])
                res["status"] = "✅ 적중" if pk_m > pk_b else "❌ 빗나감 (2단계 미충족)"
        res["chart_title"] = "Excess return vs. KOSPI (%p)"
        plot(t, [(g, excess[g], SERIES[i], False) for i, g in enumerate(t["groups"])], base, res, unit="%p")

    elif t["type"] == "outperform":
        g = next(iter(groups))
        di = nth_trading_day(dates, base, t["interim_days"])
        res["judge_date"] = f"D+{t['interim_days']} / {t['final_date']}"
        res["now"] = f"초과수익 {fmt(excess[g][last])}p"
        parts = []
        if di is not None:
            parts.append("중간 " + ("✅" if excess[g][di] > 0 else "❌"))
        if last >= t["final_date"]:
            fin = excess[g][max(d for d in excess[g] if d <= t["final_date"])]
            res["status"] = ("✅ 적중" if fin > 0 else "❌ 빗나감") + (f" ({parts[0]})" if parts else "")
        else:
            res["status"] = "⏳ 진행 중" + (f" · {parts[0]}" if parts else "")
        res["chart_title"] = "Robotics basket vs. KOSPI"
        plot(t, [(g, groups[g], SERIES[0], False), ("KOSPI", bench, BENCH, True)], base, res)

    elif t["type"] == "relative":
        a, b = list(t["groups"])
        ko = {"Cosmetics": "화장품", "Semis": "반도체"}
        cur = groups[a][last] - groups[b][last]
        res["judge_date"] = t["final_date"]
        res["now"] = f"{ko.get(a, a)} {fmt(groups[a][last])} · {ko.get(b, b)} {fmt(groups[b][last])} (차 {fmt(cur)}p)"
        if last >= t["final_date"]:
            fd = max(d for d in groups[a] if d <= t["final_date"])
            res["status"] = "✅ 적중" if groups[a][fd] > groups[b][fd] else "❌ 빗나감"
        else:
            res["status"] = "⏳ 진행 중" + (" · 앞섬" if cur > 0 else " · 뒤짐" if cur < 0 else "")
        res["chart_title"] = f"{a} vs. {b} basket"
        plot(t, [(a, groups[a], SERIES[1], False), (b, groups[b], SERIES[0], False),
                 ("KOSPI", bench, BENCH, True)], base, res)

    res["chart"] = f"tracking/charts/{t['id']}.png"
    return res


def evaluate_level(t, px):
    """금리 등 수준 변수의 구간 전망"""
    ser = px[t["series"]]
    ds = sorted(ser)
    last = ds[-1]
    lo, hi, pt = t["low"], t["high"], t["point"]
    res = {"id": t["id"], "title": t["title"], "baseline": t["baseline"], "last": last,
           "judge_date": t["target_date"]}
    res["now"] = f"{ser[last]:.2f}% ({last[5:].replace('-', '/')}) · 범위 {lo:.2f}~{hi:.2f}%"
    if t["target_date"] in ser:
        v = ser[t["target_date"]]
        err = (v - pt) * 100
        res["status"] = ("✅ 적중" if lo <= v <= hi else "❌ 빗나감") + f" (오차 {err:+.0f}bp)"
    else:
        res["status"] = "⏳ 진행 중" + (" · 범위 안" if lo <= ser[last] <= hi else " · 범위 밖")

    fig, ax = plt.subplots(figsize=(6.4, 3.2), dpi=150)
    xs = list(range(len(ds)))
    ax.axhspan(lo, hi, color="#eef3fb", zorder=0)
    ax.axhline(pt, color=SERIES[1], linewidth=1.2, linestyle="--", zorder=2, label=f"AR forecast {pt:.2f}%")
    ax.plot(xs, [ser[d] for d in ds], color=SERIES[0], linewidth=2, zorder=3, label="DGS10")
    ax.plot(xs[-1], ser[last], "o", ms=4, color=SERIES[0], zorder=4)
    ax.annotate(f"{ser[last]:.2f}%", (xs[-1], ser[last]), xytext=(6, 0), textcoords="offset points",
                va="center", fontsize=8, color=TEXT)
    bx = ds.index(t["baseline"]) if t["baseline"] in ds else None
    if bx is not None:
        ax.axvline(bx, color=TEXT2, linewidth=0.8, linestyle=":")
        ax.annotate(f"baseline {t['baseline'][5:].replace('-', '/')}", (bx, 0), xycoords=("data", "axes fraction"),
                    xytext=(-3, 4), textcoords="offset points", ha="right", fontsize=7, color=TEXT2)
    ax.set_xticks(xs)
    ax.set_xticklabels([d[5:].replace("-", "/") for d in ds])
    ax.set_xlim(-0.3, len(ds) - 1 + 0.9)
    ax.set_title(f"{t['id']}  U.S. 10Y yield · band {lo:.2f}–{hi:.2f}% · target {t['target_date'][5:].replace('-', '/')}", loc="left", fontsize=10, color=TEXT, pad=8)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color("#bdbdbd")
    ax.tick_params(colors=TEXT2, labelsize=8)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.2f}%"))
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.12), ncol=3, frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(CHARTS / f"{t['id']}.png", facecolor="white")
    plt.close(fig)
    res["chart"] = f"tracking/charts/{t['id']}.png"
    return res


def write_doc(t, r, names):
    lines = [
        f"# {t['id']} {t['title']}",
        "",
        f"- **등록일:** {t['created']} · **출처:** [{t['source_report'].split('/')[-1]}](../{t['source_report']})",
        f"- **기준일:** {t['baseline']}" + ("" if t["type"] in ("event", "level_interval") else " 종가") + f" ({t.get('baseline_note', '리포트 발행 07:00, 장 시작 전 작성')})",
        f"- **벤치마크:** {t['benchmark']}",
        "",
        "## 전망",
        "",
        f"> {t['statement']}",
        "",
        "## 판정 기준 (사전 확정)",
        "",
        t["rule"],
        "",
    ]
    if t["type"] == "level_interval":
        lines += ["## 관찰 대상", "", f"{names.get(t['series'], t['series'])}", "",
                  "## 현재 상태", "", f"{r['status']} — {r['now']}", "",
                  f"![{t['id']}](../{r['chart']})", "",
                  "*데이터: FRED DGS10 (미 연준 H.15). FRED 게시 지연으로 최근 1~2일이 빠질 수 있음.*", ""]
    elif t["groups"]:
        lines += ["## 관찰 대상", "", "| 그룹 | 종목 |", "|---|---|"]
        for g, cs in t["groups"].items():
            lines.append(f"| {g} | " + ", ".join(f"{names.get(c, c)} ({c})" for c in cs) + " |")
        lines += ["", "## 현재 상태", "", f"{r['status']} — {r['now']} (기준: {r['last']} 종가)", "",
                  f"![{t['id']}](../{r['chart']})", "",
                  "*동일가중 바스켓, 배당·비용 미반영. 데이터: KRX 일별 종가.*", ""]
    else:
        lines += ["## 현재 상태", "", f"{r['status']} — {r['now']}", ""]
    (THESES_DIR / f"{t['id']}.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    db = json.loads(DB.read_text(encoding="utf-8"))
    px = load_prices()
    CHARTS.mkdir(parents=True, exist_ok=True)
    THESES_DIR.mkdir(exist_ok=True)
    out = []
    for t in db["theses"]:
        r = evaluate(t, px)
        write_doc(t, r, db["names"])
        r.pop("chart_title", None)
        out.append(r)
    STATUS.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for r in out:
        print(r["id"], r["status"], "|", r["now"])


if __name__ == "__main__":
    main()
