"""Fill missing fund facts / company fundamentals in quotes.json and write news.json.

Existing values are kept (they came from ChartRow); Yahoo Finance only fills gaps,
so newly added tickers get complete records. News: latest headlines per stock,
with a simple keyword tone (+1 positive / -1 negative / 0 neutral).
"""
import json, re, datetime as dt
import pandas as pd, yfinance as yf

q = json.load(open("quotes.json"))
items = [i for i in q["items"] if i.get("t") and i["t"] != "USDTHB"]
now = dt.datetime.now(dt.timezone.utc)

def num(v, k=1, dp=2):
    try:
        v = float(v)
        return None if pd.isna(v) else round(v * k, dp)
    except (TypeError, ValueError):
        return None

def money(v):
    v = num(v, 1, 0)
    if not v: return None
    for d, u in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if v >= d: return f"{v / d:.1f}{u}"

SECT = {"technology": "Technology", "healthcare": "Healthcare", "financial_services": "Financials",
        "consumer_cyclical": "Consumer Discretionary", "consumer_defensive": "Consumer Staples",
        "communication_services": "Communication Services", "industrials": "Industrials",
        "energy": "Energy", "basic_materials": "Materials", "realestate": "Real Estate",
        "utilities": "Utilities"}

def cagr_rows(df, names):
    for n in names:
        if df is not None and n in df.index:
            s = df.loc[n].dropna().sort_index()
            if len(s) >= 3 and s.iloc[0] > 0 and s.iloc[-1] > 0:
                yrs = (s.index[-1] - s.index[0]).days / 365.25
                return round(((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100, 1)
    return None

def fill(it, k, v):
    if v is not None and it.get(k) is None:
        it[k] = v

for it in items:
    t = it["t"]
    stk = it.get("k") == "stk"
    need = ["mcap", "pe", "fpe", "nm", "beta", "sector"] if stk else ["er", "aum", "top", "sec", "inc"]
    if all(it.get(k) is not None for k in need):
        continue
    try:
        tk = yf.Ticker(t); info = tk.info or {}
        if stk:
            fill(it, "mcap", money(info.get("marketCap")))
            fill(it, "pe", num(info.get("trailingPE"), 1, 1))
            fill(it, "fpe", num(info.get("forwardPE"), 1, 1))
            fill(it, "nm", num(info.get("profitMargins"), 100, 1))
            fill(it, "roe", num(info.get("returnOnEquity"), 100, 1))
            de = num(info.get("debtToEquity"), 0.01)
            fill(it, "de", de)
            fcf, cap = num(info.get("freeCashflow"), 1, 0), num(info.get("marketCap"), 1, 0)
            fill(it, "fcfy", round(fcf / cap * 100, 1) if fcf and cap else None)
            fill(it, "y", num(info.get("trailingAnnualDividendYield"), 100, 2))
            fill(it, "beta", num(info.get("beta")))
            fill(it, "sector", info.get("sector"))
            fill(it, "n", info.get("shortName"))
            try:
                inc = tk.income_stmt
                fill(it, "rev5", cagr_rows(inc, ["Total Revenue"]))
                fill(it, "eps5", cagr_rows(inc, ["Diluted EPS"]))
            except Exception:
                pass
        else:
            fill(it, "er", num(info.get("netExpenseRatio"), 1, 2))
            fill(it, "aum", money(info.get("totalAssets")))
            fill(it, "y", num(info.get("yield"), 100, 2))
            d0 = info.get("fundInceptionDate")
            fill(it, "inc", str(dt.datetime.fromtimestamp(d0, dt.timezone.utc).year) if d0 else None)
            fill(it, "n", info.get("longName") or info.get("shortName"))
            fd = tk.funds_data
            th = fd.top_holdings
            if th is not None and len(th):
                col = [c for c in th.columns if "ercent" in c][0]
                fill(it, "top", [{"s": str(s), "w": round(float(w) * 100, 1)} for s, w in th[col].head(5).items()])
                fill(it, "t10", round(float(th[col].head(10).sum()) * 100, 1))
            sw = fd.sector_weightings or {}
            if sw:
                top4 = sorted(sw.items(), key=lambda x: -x[1])[:4]
                fill(it, "sec", [{"s": SECT.get(k, k.title()), "w": round(v * 100, 1)} for k, v in top4 if v > 0])
        print("filled", t, {k: it.get(k) for k in need})
    except Exception as e:
        print("fill failed", t, e)

json.dump(q, open("quotes.json", "w"), ensure_ascii=False, separators=(",", ":"))

POS = r"beat|beats|surge|soar|jump|rall|record|upgrade|raise[sd]? (guidance|outlook|target)|strong|growth|wins?|approval|approved|buy rating|outperform|profit rise|tops"
NEG = r"miss|plunge|slump|tumble|fall|falls|drop|downgrade|cut[s]? (guidance|outlook|target)|lawsuit|probe|investigation|recall|weak|loss|layoff|antitrust|fine[ds]?|warn|sell-off|selloff|underperform|halt"

news = {}
for it in [i for i in items if i.get("k") == "stk"]:
    t = it["t"]; out = []
    try:
        for n in (yf.Ticker(t).news or [])[:12]:
            c = n.get("content", n)
            title = c.get("title"); 
            if not title: continue
            url = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or c.get("link")
            src = (c.get("provider") or {}).get("displayName") or c.get("publisher") or ""
            when = c.get("pubDate") or c.get("displayTime")
            if not when and n.get("providerPublishTime"):
                when = dt.datetime.fromtimestamp(n["providerPublishTime"], dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            low = title.lower()
            tone = (1 if re.search(POS, low) else 0) - (1 if re.search(NEG, low) else 0)
            if url and url.startswith("http"):
                out.append({"h": title[:200], "s": src[:40], "u": url, "t": when, "tone": tone})
    except Exception as e:
        print("news failed", t, e)
    out.sort(key=lambda x: x.get("t") or "", reverse=True)
    news[t] = out[:6]
json.dump({"updatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "items": news},
          open("news.json", "w"), ensure_ascii=False, separators=(",", ":"))
print("news for", sum(1 for v in news.values() if v), "of", len(news), "stocks")
