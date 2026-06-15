"""섹터/업종 저평가 스크리너 — 섹터/업종 종목을 저평가 점수순 정렬."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from . import universe as U
from . import scoring


def _avg(vals):
    v = [x for x in vals if isinstance(x, (int, float)) and x > 0]
    return sum(v) / len(v) if v else None


def screen(members: list[dict], corpmap: dict, dart_key: str, progress=None) -> dict:
    rows = []
    total = len(members)
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, c in enumerate(ex.map(lambda e: U.enrich(e, corpmap, dart_key), members)):
            rows.append(c)
            if progress:
                progress((i + 1) / total)
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
        warnings.append(f"{missing}개 종목 재무 미조회 → 저평가 0점 처리(하위 배치).")
    return {"rows": rows, "warnings": warnings, "peer": peer}


def sector_screen(sector: str, corpmap: dict, dart_key: str, progress=None) -> dict:
    members = [e for e in U.UNIVERSE if e["sector"] == sector]
    res = screen(members, corpmap, dart_key, progress)
    res["label"] = U.sector_label(sector)
    return res


def industry_screen(industry: str, corpmap: dict, dart_key: str, progress=None) -> dict:
    members = [e for e in U.UNIVERSE if e["industry"] == industry]
    res = screen(members, corpmap, dart_key, progress)
    res["label"] = U.industry_label(industry)
    return res
