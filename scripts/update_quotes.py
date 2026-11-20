"""Refresh prices in quotes.json from Yahoo Finance.

Updates only price-driven fields (d, p, pr, tr, lo, hi, m20, m50, cg) and the
USD/THB rate. Fund facts (er, aum, holdings) and stock fundamentals are kept.
"""
import json, sys, datetime as dt
import pandas as pd, yfinance as yf

PATH = "quotes.json"
q = json.load(open(PATH))
items = q["items"]
tickers = [i["t"] for i in items if i.get("t") and i["t"] != "USDTHB"]

raw = yf.download(tickers + ["THB=X"], period="16y", interval="1d",
                  auto_adjust=False, group_by="ticker", progress=False, threads=True)

def pct(a, b):
    return None if b is None or not b or pd.isna(b) else round((a / b - 1) * 100, 2)

def at_or_before(s, when):
    s = s[s.index <= when]
    return None if s.empty else float(s.iloc[-1])

def returns(s, last):
    s = s.dropna()
    v, t = float(s.iloc[-1]), s.index[-1]
    prev_year_end = at_or_before(s, pd.Timestamp(t.year - 1, 12, 31))
    return {
        "d1": pct(v, float(s.iloc[-2])) if len(s) > 1 else None,
        "d5": pct(v, float(s.iloc[-6])) if len(s) > 5 else None,
        "m1": pct(v, at_or_before(s, t - pd.DateOffset(months=1))),
        "m3": pct(v, at_or_before(s, t - pd.DateOffset(months=3))),
        "ytd": pct(v, prev_year_end),
        "y1": pct(v, at_or_before(s, t - pd.DateOffset(years=1))),
        "y5": pct(v, at_or_before(s, t - pd.DateOffset(years=5))),
    }

def cagr(s, years):
    s = s.dropna(); t = s.index[-1]
    if s.index[0] > t - pd.DateOffset(years=years) + pd.Timedelta(days=7):
        return None
    b = at_or_before(s, t - pd.DateOffset(years=years))
    return round(((float(s.iloc[-1]) / b) ** (1 / years) - 1) * 100, 1) if b else None

now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
updated, skipped = 0, []
for it in items:
    t = it.get("t")
    if not t or t == "USDTHB":
        continue
    try:
        df = raw[t].dropna(subset=["Close"])
        close, adj = df["Close"], df["Adj Close"]
        p, d = round(float(close.iloc[-1]), 2), close.index[-1].strftime("%Y-%m-%d")
        if it.get("p") and abs(p / it["p"] - 1) > 0.4:
            skipped.append(f"{t}: price jump {it['p']}->{p}"); continue
        if d < it.get("d", "") or (d == it.get("d") and p == it.get("p")):
            continue
        yr = df[df.index > df.index[-1] - pd.DateOffset(years=1)]
        it.update(d=d, p=p, pr=returns(close, p),
                  lo=round(float(yr["Low"].min()), 2), hi=round(float(yr["High"].max()), 2),
                  m50=round(float(close.iloc[-50:].mean()), 2), fetchedAt=now, src="yahoo")
        if it.get("k") != "stk":
            it.update(tr=returns(adj, p), m20=round(float(close.iloc[-20:].mean()), 2),
                      cg=[cagr(adj, y) for y in (1, 2, 3, 5, 10, 15)])
        updated += 1
    except Exception as e:
        skipped.append(f"{t}: {e}")

fx = next((i for i in items if i.get("t") == "USDTHB"), None)
try:
    r = round(float(raw["THB=X"]["Close"].dropna().iloc[-1]), 2)
    if 20 < r < 60 and fx:
        fx.update(rate=r, d=now[:10], fetchedAt=now, src="yahoo")
except Exception as e:
    skipped.append(f"USDTHB: {e}")

if updated == 0 and skipped and len(skipped) >= len(tickers):
    print("All fetches failed:", skipped[:5]); sys.exit(1)
q["updatedAt"] = max(i.get("fetchedAt", "") for i in items)
json.dump(q, open(PATH, "w"), ensure_ascii=False, separators=(",", ":"))
print(f"updated {updated}/{len(tickers)}; skipped: {skipped}")
