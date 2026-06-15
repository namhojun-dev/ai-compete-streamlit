"""미국주식 재무 — Yahoo quoteSummary (crumb + cookie). ROE/마진은 %로 변환."""
from __future__ import annotations
import threading
import requests

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_session: requests.Session | None = None
_crumb: str = ""
_lock = threading.Lock()


def _ensure():
    global _session, _crumb
    if _session is not None and _crumb:
        return
    s = requests.Session()
    s.headers.update({"User-Agent": _UA})
    for seed in ("https://fc.yahoo.com", "https://finance.yahoo.com"):
        try:
            s.get(seed, timeout=10)
            break
        except Exception:
            continue
    try:
        _crumb = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10).text.strip()
    except Exception:
        _crumb = ""
    _session = s


def _raw(d, k):
    x = d.get(k) if d else None
    return x.get("raw") if isinstance(x, dict) else x


def get_us_fundamentals(symbol: str) -> dict:
    with _lock:
        _ensure()
        s, crumb = _session, _crumb
    out = {"symbol": symbol, "price": None, "per": None, "eps": None, "pbr": None,
           "roe": None, "operatingMargin": None, "netMargin": None,
           "revenueGrowthYoY": None, "marketCap": None}
    if not crumb:
        return out
    url = (f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
           f"?modules=price,summaryDetail,defaultKeyStatistics,financialData&crumb={crumb}")
    try:
        r = s.get(url, timeout=12)
        if r.status_code != 200:
            return out
        res = r.json().get("quoteSummary", {}).get("result") or []
        if not res:
            return out
        res = res[0]
    except Exception:
        return out
    pr, sd = res.get("price", {}), res.get("summaryDetail", {})
    ks, fd = res.get("defaultKeyStatistics", {}), res.get("financialData", {})
    price = _raw(pr, "regularMarketPrice")
    eps = _raw(ks, "trailingEps")
    per = _raw(sd, "trailingPE")
    if per is None and price and eps and eps > 0:
        per = price / eps
    roe, opm, nm, rg = (_raw(fd, "returnOnEquity"), _raw(fd, "operatingMargins"),
                        _raw(fd, "profitMargins"), _raw(fd, "revenueGrowth"))
    out.update({
        "price": price, "per": per, "eps": eps, "pbr": _raw(ks, "priceToBook"),
        "roe": roe * 100 if roe is not None else None,
        "operatingMargin": opm * 100 if opm is not None else None,
        "netMargin": nm * 100 if nm is not None else None,
        "revenueGrowthYoY": rg * 100 if rg is not None else None,
        "marketCap": _raw(pr, "marketCap"),
    })
    return out
