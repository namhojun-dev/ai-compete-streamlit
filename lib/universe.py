"""국내 종목 유니버스 로드 + 섹터/업종 라벨 + 재무 보강(Yahoo 가격 + DART)."""
from __future__ import annotations
import json
import os
from . import market, dart

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(_DIR, "data", "universe.json"), encoding="utf-8") as f:
    UNIVERSE = json.load(f)

SECTOR_LABELS = {
    "Technology": "기술 · IT · 반도체",
    "Healthcare": "헬스케어 · 제약 · 바이오",
    "Financial Services": "금융 · 증권 · 보험",
    "Consumer Cyclical": "경기소비재 · 유통 · 자동차",
    "Consumer Defensive": "필수소비재 · 식품 · 화장품",
    "Basic Materials": "소재 · 화학 · 철강",
    "Industrials": "산업재 · 기계 · 조선 · 건설",
    "Communication Services": "커뮤니케이션 · 게임 · 통신 · 엔터",
    "Energy": "에너지",
    "Utilities": "유틸리티",
}

INDUSTRY_LABELS = {
    "Consumer Electronics": "가전 · 전자", "Semiconductors": "반도체",
    "Electronic Components": "전자부품", "Information Technology Services": "IT 서비스",
    "Semiconductor Equipment & Materials": "반도체 장비·소재",
    "Scientific & Technical Instruments": "계측 · 정밀기기",
    "Software—Application": "응용 SW", "Software—Infrastructure": "인프라 SW",
    "Drug Manufacturers—General": "제약 (대형)",
    "Drug Manufacturers—Specialty & Generic": "제약 (전문·제네릭)",
    "Biotechnology": "바이오텍", "Medical Devices": "의료기기",
    "Banks—Regional": "은행", "Capital Markets": "증권",
    "Insurance—Life": "생명보험", "Insurance—Property & Casualty": "손해보험",
    "Insurance—Diversified": "종합보험 · 금융",
    "Auto Manufacturers": "완성차", "Auto Parts": "자동차부품",
    "Department Stores": "백화점 · 유통", "Lodging": "호텔 · 레저",
    "Household & Personal Products": "화장품 · 생활용품", "Packaged Foods": "식품",
    "Beverages—Non-Alcoholic": "음료", "Beverages—Wineries & Distilleries": "주류",
    "Grocery Stores": "편의점 · 마트", "Confectioners": "제과",
    "Steel": "철강", "Specialty Chemicals": "화학 · 소재",
    "Other Industrial Metals & Mining": "비철금속",
    "Electrical Equipment & Parts": "전기 · 중전기",
    "Specialty Industrial Machinery": "조선 · 기계", "Aerospace & Defense": "항공 · 방산",
    "Railroads": "철도", "Engineering & Construction": "건설",
    "Integrated Freight & Logistics": "물류",
    "Farm & Heavy Construction Machinery": "건설기계",
    "Internet Content & Information": "인터넷 · 플랫폼",
    "Electronic Gaming & Multimedia": "게임", "Entertainment": "엔터 · 콘텐츠",
    "Telecom Services": "통신", "Advertising Agencies": "광고",
    "Oil & Gas Refining & Marketing": "정유",
}


def sector_label(s: str) -> str:
    return SECTOR_LABELS.get(s, s)


def industry_label(s: str) -> str:
    return INDUSTRY_LABELS.get(s, s)


def get_sectors() -> list[dict]:
    """섹터 → 하위 업종(2종목 이상) 트리."""
    by_sector: dict[str, dict[str, int]] = {}
    for e in UNIVERSE:
        by_sector.setdefault(e["sector"], {})
        by_sector[e["sector"]][e["industry"]] = by_sector[e["sector"]].get(e["industry"], 0) + 1
    out = []
    for sector, inds in by_sector.items():
        industries = [{"industry": i, "label": industry_label(i), "count": c}
                      for i, c in inds.items() if c >= 2]
        industries.sort(key=lambda x: -x["count"])
        out.append({"sector": sector, "label": sector_label(sector),
                    "count": sum(inds.values()), "industries": industries})
    out.sort(key=lambda x: -x["count"])
    return out


def find_by_code(code: str):
    return next((e for e in UNIVERSE if e["code"] == code), None)


def find_by_name(name: str):
    n = name.replace(" ", "").lower()
    for e in UNIVERSE:
        if e["name"].replace(" ", "").lower() == n:
            return e
    for e in UNIVERSE:
        en = e["name"].replace(" ", "").lower()
        if n and (n in en or en in n):
            return e
    return None


def enrich(entry: dict, corpmap: dict, dart_key: str) -> dict:
    """유니버스 항목에 Yahoo 가격 + DART 재무를 붙여 비교/스크리너용 dict 생성."""
    px = market.get_price(entry["ticker"])
    code = entry["code"]
    m = dart.get_dart_metrics(corpmap.get(code, ""), dart_key) if corpmap else None
    eps = m["eps"] if m else None
    price = px["price"]
    per = (price / eps) if (price is not None and eps and eps > 0) else None
    pbr = (price / m["bps"]) if (m and price is not None and m.get("bps") and m["bps"] > 0) else None
    fin_present = sum(1 for v in [per, eps, pbr, (m or {}).get("roe"),
                                  (m or {}).get("operatingMargin"), (m or {}).get("revenueGrowthYoY")] if v is not None)
    return {
        "code": code, "ticker": entry["ticker"], "name": entry["name"], "market": entry["market"],
        "sector": entry["sector"], "industry": entry["industry"], "mainProducts": entry.get("mainProducts", []),
        "price": price, "per": per, "eps": eps, "pbr": pbr,
        "roe": (m or {}).get("roe"), "operatingMargin": (m or {}).get("operatingMargin"),
        "netMargin": (m or {}).get("netMargin"), "revenueGrowthYoY": (m or {}).get("revenueGrowthYoY"),
        "marketCap": None,
        "financials": "ok" if fin_present >= 4 else ("partial" if fin_present > 0 else "missing"),
    }
