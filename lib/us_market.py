"""미국주식 재무 — SEC EDGAR XBRL(키 없음·Cloud에서 차단 안 됨) 우선, 가격은 Yahoo v8 차트.

Yahoo quoteSummary/yfinance는 Streamlit Cloud 데이터센터 IP를 401(Invalid Crumb)로 차단하므로
재무는 SEC companyfacts에서 계산. 로컬 등 비차단 환경에서는 yfinance 폴백도 사용.
"""
from __future__ import annotations
import os
import threading
import requests

_UA = os.environ.get("SEC_USER_AGENT") or "ai-compete research contact@example.com"
_HDR = {"User-Agent": _UA, "Accept": "application/json"}
_lock = threading.Lock()
_cik_cache: dict | None = None


def _blank(symbol):
    return {"symbol": symbol, "price": None, "per": None, "eps": None, "pbr": None,
            "roe": None, "operatingMargin": None, "netMargin": None,
            "revenueGrowthYoY": None, "marketCap": None}


def _chart_price(symbol):
    """Yahoo v8 차트 — Cloud에서도 통과되는 가격 소스."""
    try:
        from . import market
        px = market.get_price(symbol)
        return px.get("price") if px else None
    except Exception:
        return None


def _cik_for(symbol: str):
    global _cik_cache
    with _lock:
        if _cik_cache is None:
            try:
                r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=_HDR, timeout=15)
                data = r.json()
                _cik_cache = {str(v["ticker"]).upper(): int(v["cik_str"]) for v in data.values()}
            except Exception:
                _cik_cache = {}
    s = symbol.upper()
    return _cik_cache.get(s) or _cik_cache.get(s.replace("-", ".")) or _cik_cache.get(s.replace(".", "-"))


def _facts(cik: int):
    try:
        r = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", headers=_HDR, timeout=20)
        if r.status_code != 200:
            return None
        return r.json().get("facts", {})
    except Exception:
        return None


def _annual(block, concept, unit):
    """연간(10-K/20-F, FY) 값들을 end 기준 정렬해 반환."""
    arr = block.get(concept, {}).get("units", {}).get(unit, [])
    fy = [x for x in arr if x.get("fp") == "FY" and x.get("form") in ("10-K", "10-K/A", "20-F", "40-F")]
    seen, out = set(), []
    for x in sorted(fy, key=lambda v: v.get("end", "")):
        key = x.get("end")
        out = [o for o in out if o.get("end") != key]  # 같은 end 최신으로 교체
        out.append(x)
    return out


def _latest_instant(block, concept, unit):
    arr = sorted(block.get(concept, {}).get("units", {}).get(unit, []), key=lambda v: v.get("end", ""))
    return arr[-1]["val"] if arr else None


def _first_annual(block, concepts, unit):
    for c in concepts:
        a = _annual(block, c, unit)
        if a:
            return a
    return []


def _from_sec(symbol: str) -> dict | None:
    cik = _cik_for(symbol)
    if not cik:
        return None
    facts = _facts(cik)
    if not facts:
        return None
    g = facts.get("us-gaap", {})
    dei = facts.get("dei", {})

    eps_a = _first_annual(g, ["EarningsPerShareDiluted", "EarningsPerShareBasic"], "USD/shares")
    ni_a = _annual(g, "NetIncomeLoss", "USD")
    rev_a = _first_annual(g, ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"], "USD")
    op_a = _annual(g, "OperatingIncomeLoss", "USD")
    equity = _latest_instant(g, "StockholdersEquity", "USD")
    shares = (_latest_instant(dei, "EntityCommonStockSharesOutstanding", "shares")
              or _latest_instant(g, "WeightedAverageNumberOfDilutedSharesOutstanding", "shares"))

    # 모든 손익 항목을 같은 회계연도(anchor end)에 정렬 — 연도 불일치로 인한 비율 왜곡 방지
    anchor = ((rev_a or ni_a or eps_a or [{}])[-1]).get("end")

    def at(lst, end):
        if not lst:
            return None
        exact = [x for x in lst if x.get("end") == end]
        if exact:
            return exact[-1]["val"]
        le = [x for x in lst if x.get("end", "") <= (end or "")]
        return (le[-1] if le else lst[-1])["val"]

    eps = at(eps_a, anchor)
    ni = at(ni_a, anchor)
    rev = at(rev_a, anchor)
    op = at(op_a, anchor)
    prev = [x for x in rev_a if x.get("end", "") < (anchor or "")]
    rev_prev = prev[-1]["val"] if prev else None

    if eps is None and ni is None and equity is None:
        return None
    out = _blank(symbol)
    out["eps"] = eps
    out["roe"] = (ni / equity * 100) if (ni is not None and equity) else None
    out["operatingMargin"] = (op / rev * 100) if (op is not None and rev) else None
    out["netMargin"] = (ni / rev * 100) if (ni is not None and rev) else None
    out["revenueGrowthYoY"] = ((rev - rev_prev) / rev_prev * 100) if (rev and rev_prev) else None
    out["_bvps"] = (equity / shares) if (equity and shares) else None
    out["_shares"] = shares
    return out


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


def get_us_fundamentals(symbol: str) -> dict:
    # 1순위: SEC(키 없음·Cloud 차단 안 됨) 재무 + 차트 가격
    sec = _from_sec(symbol)
    if sec:
        price = _chart_price(symbol)
        sec["price"] = price
        if price and sec.get("eps") and sec["eps"] > 0:
            sec["per"] = price / sec["eps"]
        if price and sec.get("_bvps") and sec["_bvps"] > 0:
            sec["pbr"] = price / sec["_bvps"]
        if price and sec.get("_shares"):
            sec["marketCap"] = price * sec["_shares"]
        sec.pop("_bvps", None)
        sec.pop("_shares", None)
        return sec
    # 2순위: yfinance(로컬 등 비차단 환경)
    yf = _from_yfinance(symbol)
    if yf:
        if yf["price"] is None:
            yf["price"] = _chart_price(symbol)
        return yf
    # 최후: 가격만
    blank = _blank(symbol)
    blank["price"] = _chart_price(symbol)
    return blank
