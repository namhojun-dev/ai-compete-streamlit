"""미국 저평가 스크리너 — Yahoo 재무로 섹터 종목을 저평가 점수순 정렬."""
from __future__ import annotations
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from . import us_market, scoring

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(_DIR, "data", "us_universe.json"), encoding="utf-8") as f:
    US_UNIVERSE = json.load(f)


def _avg(vals):
    v = [x for x in vals if isinstance(x, (int, float)) and x > 0]
    return sum(v) / len(v) if v else None


def us_sectors() -> list[tuple[str, int]]:
    c = Counter(e["sector"] for e in US_UNIVERSE)
    return sorted(c.items(), key=lambda x: -x[1])


def screen_us(sector: str) -> dict:
    members = [e for e in US_UNIVERSE if e["sector"] == sector]
    with ThreadPoolExecutor(max_workers=8) as ex:
        funds = list(ex.map(lambda e: us_market.get_us_fundamentals(e["symbol"]), members))
    rows = []
    for e, f in zip(members, funds):
        row = {**e, **f}
        row["financials"] = "ok" if (f["per"] and f["per"] > 0) else "missing"
        rows.append(row)
    peer = {"per": _avg([r["per"] for r in rows]), "eps": _avg([r["eps"] for r in rows])}
    missing = 0
    for c in rows:
        if c["financials"] == "missing":
            missing += 1
        vs, reason = scoring.score_valuation(c, peer)
        c["valuationScore"] = vs
        c["qualityScore"] = scoring.quality_score(c)
        c["reason"] = reason
    rows.sort(key=lambda c: (c["valuationScore"], c["qualityScore"]), reverse=True)
    for i, c in enumerate(rows):
        c["rank"] = i + 1
    warnings = []
    if missing:
        warnings.append(f"{missing}개 종목 PER 미조회/적자 → 저평가 0점 처리(하위 배치).")
    return {"rows": rows, "warnings": warnings, "peer": peer, "sector": sector}
