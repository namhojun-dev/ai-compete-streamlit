"""미국주식 재무 — yfinance 우선(Cloud 견고) + Yahoo quoteSummary 폴백. ROE/마진은 %로 변환."""
from __future__ import annotations
import threading
import requests

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_session: requests.Session | None = None
_crumb: str = ""
_lock = threading.Lock()


def _blank(symbol):
    return {"symbol": symbol, "price": None, "per": None, "eps": None, "pbr": None,
            "roe": None, "operatingMargin": None, "netMargin": None,
            "revenueGrowthYoY": None, "marketCap": None}


def _pct(x):
    return x * 100 if isinstance(x, (int, float)) else None


def _from_yfinance(symbol: str) -> dict | None:
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
    except Exception:
        return None
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    eps = info.get("trailingEps")
    per = info.get("trailingPE")
    if per is None and price and eps and eps > 0:
        per = price / eps
    if price is None and per is None:
        return None
    return {"symbol": symbol, "price": price, "per": per, "eps": eps,
            "pbr": info.get("priceToBook"), "roe": _pct(info.get("returnOnEquity")),
            "operatingMargin": _pct(info.get("operatingMargins")),
            "netMargin": _pct(info.get("profitMargins")),
            "revenueGrowthYoY": _pct(info.get("revenueGrowth")),
            "marketCap": info.get("marketCap")}


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


def _from_quotesummary(symbol: str) -> dict | None:
    with _lock:
        _ensure()
        s, crumb = _session, _crumb
    if not crumb:
        return None
    url = (f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
           f"?modules=price,summaryDetail,defaultKeyStatistics,financialData&crumb={crumb}")
    try:
        r = s.get(url, timeout=12)
        if r.status_code != 200:
            return None
        res = r.json().get("quoteSummary", {}).get("result") or []
        if not res:
            return None
        res = res[0]
    except Exception:
        return None
    pr, sd = res.get("price", {}), res.get("summaryDetail", {})
    ks, fd = res.get("defaultKeyStatistics", {}), res.get("financialData", {})
    price = _raw(pr, "regularMarketPrice")
    eps = _raw(ks, "trailingEps")
    per = _raw(sd, "trailingPE")
    if per is None and price and eps and eps > 0:
        per = price / eps
    return {"symbol": symbol, "price": price, "per": per, "eps": eps, "pbr": _raw(ks, "priceToBook"),
            "roe": _pct(_raw(fd, "returnOnEquity")), "operatingMargin": _pct(_raw(fd, "operatingMargins")),
            "netMargin": _pct(_raw(fd, "profitMargins")), "revenueGrowthYoY": _pct(_raw(fd, "revenueGrowth")),
            "marketCap": _raw(pr, "marketCap")}


def get_us_fundamentals(symbol: str) -> dict:
    out = _from_yfinance(symbol) or _from_quotesummary(symbol)
    if out:
        return out
    # 최후: 가격만이라도 v8 차트로
    blank = _blank(symbol)
    try:
        from . import market
        px = market.get_price(symbol)
        if px:
            blank["price"] = px.get("price")
    except Exception:
        pass
    return blank
