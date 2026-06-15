"""Yahoo Finance 시세(키 불필요). 한국 종목 PER/EPS는 DART가 채우고, 여기선 현재가만."""
from __future__ import annotations
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"


def get_price(symbol: str) -> dict:
    """{'price','name','currency'} — v8 chart 엔드포인트(키 불필요)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=8)
        if r.status_code != 200:
            return {"price": None, "name": None, "currency": None, "quoteType": None}
        meta = (r.json().get("chart", {}).get("result") or [{}])[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        return {
            "price": price if isinstance(price, (int, float)) else None,
            "name": meta.get("longName") or meta.get("shortName"),
            "currency": meta.get("currency"),
            "quoteType": meta.get("instrumentType"),
        }
    except Exception:
        return {"price": None, "name": None, "currency": None, "quoteType": None}
