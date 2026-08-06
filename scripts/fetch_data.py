#!/usr/bin/env python3
"""
抓取六大方向宽基ETF的每日份额变动数据，计算分类净申赎并生成 index.html 所需的数据快照。

数据源：恒生聚源 Gildata（ETF基金份额变动表）
使用方法：
    python3 scripts/fetch_data.py          # 抓取并更新 index.html 中的 DATA
"""
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# 监测篮子：六大方向，每个方向取规模前5（中证500全市场超50亿ETF仅4只，按实际纳入）
BASKET = {
    "上证50":  ["510050", "510100", "530000", "510710", "510800"],
    "沪深300": ["510300", "510310", "510330", "159919", "510360"],
    "中证500": ["510500", "159922", "512500", "159935"],
    "中证1000": ["512100", "560010", "159845", "159629", "159633"],
    "中证2000": ["563300", "159531", "159532", "560220", "159536"],
    "科创50":  ["588000", "588080", "588050", "588060", "588090"],
}

# 绝对值法判定阈值（单位：亿元）
BUY_STRONG, BUY_WEAK = 100, 50
SELL_STRONG, SELL_WEAK = -100, -50

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data"
WORK.mkdir(exist_ok=True)

GILDATA_TOOL = "C:/Users/ruoyu/AppData/Roaming/kimi-desktop/daimon-share/daimon/runtime/kimi-code/home/plugins/managed/gildata-aifinmarket/scripts/gildata_tool.py"


def fetch_etf(code: str) -> None:
    """通过 Gildata FinQuery 抓取单只ETF份额变动，保存到 data/etf_{code}.csv"""
    suffix = "SH" if code.startswith("5") else "SZ"
    out = WORK / f"etf_{code}.csv"
    cmd = [
        "python3", GILDATA_TOOL,
        "call", "--api-name", "gildata_fin_query",
        "--params-json", json.dumps({
            "query": f"查询{code}.{suffix}的ETF基金份额变动情况",
            "file_path": str(out),
        }),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, encoding='utf-8', errors='replace')
    if not out.exists():
        print(f"  {code} 抓取失败: {r.stdout[-200:]}", file=sys.stderr)
        sys.exit(1)
    print(f"  {code} ok")


def parse_csv(path: Path, cat: str):
    """解析 Gildata 返回的 table_markdown，返回记录列表"""
    with open(path, encoding='utf-8') as f:
        rows = list(csv.reader(f))
    md = rows[1][7]
    recs = []
    for line in md.strip().split("\n"):
        line = line.strip().strip("|")
        if not line or line.startswith("---") or line.startswith("基金代码"):
            continue
        cells = [x.strip() for x in line.split("|")]
        if len(cells) < 9 or cells[0] == "暂无数据":
            continue
        f = lambda x: None if x in ("-", "") else float(x)
        if f(cells[4]) is None or f(cells[5]) is None or f(cells[7]) is None:
            continue
        recs.append(dict(
            code=cells[0], name=cells[1], date=cells[3],
            shares=f(cells[4]), d_shares=f(cells[5]),
            pct=f(cells[6]) or 0.0, aum_wy=f(cells[7]), cat=cat,
        ))
    return recs


def verdict(total_yi: float):
    """绝对值法判定"""
    if total_yi >= BUY_STRONG:
        return ("买了", "大概率")
    if total_yi >= BUY_WEAK:
        return ("买了", "疑似")
    if total_yi <= SELL_STRONG:
        return ("卖了", "大概率")
    if total_yi <= SELL_WEAK:
        return ("卖了", "疑似")
    return ("无动作", "")


def main():
    print("1/3 抓取ETF份额数据...")
    for cat, codes in BASKET.items():
        for c in codes:
            fetch_etf(c)

    print("2/3 解析并计算...")
    all_recs, meta = [], {}
    for cat, codes in BASKET.items():
        for c in codes:
            rs = parse_csv(WORK / f"etf_{c}.csv", cat)
            for r in rs:
                r["cat"] = cat
            all_recs += rs
            meta[c] = (rs[0]["name"], cat, rs[0]["aum_wy"] / 10000)

    df = pd.DataFrame(all_recs)
    df["nav"] = df["aum_wy"] / df["shares"]
    df["flow_wy"] = df["d_shares"] * df["nav"]
    daily = df.groupby("date").agg(total_wy=("flow_wy", "sum")).reset_index()
    daily["total_yi"] = daily["total_wy"] / 10000
    daily = daily.sort_values("date").reset_index(drop=True)

    piv_flow = df.pivot_table(index="date", columns="code", values="flow_wy")
    piv_pct = df.pivot_table(index="date", columns="code", values="pct")
    piv_d = df.pivot_table(index="date", columns="code", values="d_shares")

    records = []
    for _, row in daily.tail(30).iterrows():
        d, t = row["date"], row["total_yi"]
        v, conf = verdict(t)
        etfs = []
        for cat in BASKET:
            for c in BASKET[cat]:
                name, _, aum = meta[c]
                if d in piv_flow.index and c in piv_flow.columns and not np.isnan(piv_flow.loc[d, c]):
                    etfs.append(dict(code=c, name=name, index=cat,
                                     flow_yi=round(piv_flow.loc[d, c] / 10000, 2),
                                     pct=round(piv_pct.loc[d, c], 2),
                                     d_shares_wan=round(piv_d.loc[d, c], 0),
                                     aum_yi=round(aum, 0)))
                else:
                    etfs.append(dict(code=c, name=name, index=cat, flow_yi=None,
                                     pct=None, d_shares_wan=None, aum_yi=round(aum, 0)))
        cats = []
        for cat in BASKET:
            sub = [e for e in etfs if e["index"] == cat]
            have = [e for e in sub if e["flow_yi"] is not None]
            cats.append(dict(cat=cat,
                             flow_yi=round(sum(e["flow_yi"] for e in have), 2) if have else None,
                             n_have=len(have), n_total=len(sub)))
        records.append(dict(date=d, total_yi=round(t, 2), verdict=v, confidence=conf,
                            buy_count=sum(1 for e in etfs if e["pct"] and e["pct"] >= 1.5),
                            sell_count=sum(1 for e in etfs if e["pct"] and e["pct"] <= -1.5),
                            etf_count=sum(1 for e in etfs if e["flow_yi"] is not None),
                            cats=cats, etfs=etfs))
    records.reverse()

    site_data = {
        "asof": daily.iloc[-1]["date"],
        "generated": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "n_etf": sum(len(v) for v in BASKET.values()),
        "basket": {c: {"name": meta[c][0], "cat": meta[c][1], "aum_yi": round(meta[c][2], 0)}
                   for cat in BASKET for c in BASKET[cat]},
        "records": records,
    }

    print("3/3 注入 index.html ...")
    html = (ROOT / "index.html").read_text(encoding='utf-8')
    html = re.sub(r"const DATA = .*?;\n", "const DATA = " + json.dumps(site_data, ensure_ascii=False) + ";\n",
                  html, count=1, flags=re.S)
    (ROOT / "index.html").write_text(html, encoding='utf-8')
    print(f"完成。最新数据日期 {site_data['asof']}，覆盖 {site_data['n_etf']} 只ETF。")


if __name__ == "__main__":
    main()
