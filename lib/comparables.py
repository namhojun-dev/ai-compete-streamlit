"""유사 종목 PER·EPS 비교 — 입력 종목과 유사한 국내 종목을 코스피/코스닥으로 나눠 순위화."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from . import universe as U
from . import scoring

BROAD_SECTORS = {"industrials", "basic materials", "consumer cyclical",
                 "consumer defensive", "financial services", "communication services"}
MAX_PER_MARKET = 12


def _avg(vals):
    v = [x for x in vals if isinstance(x, (int, float)) and x > 0]
    return sum(v) / len(v) if v else None


def get_comparables(input_str: str, corpmap: dict, dart_key: str, progress=None) -> dict:
    s = input_str.strip()
    # 기준 종목 찾기 (코드 또는 회사명)
    base_entry = None
    if s.isdigit() and len(s) == 6:
        base_entry = U.find_by_code(s)
    if base_entry is None:
        base_entry = U.find_by_name(s)
    if base_entry is None:
        raise ValueError(f"'{input_str}' 종목을 유니버스에서 찾지 못했습니다. 6자리 코드나 등록된 회사명으로 입력하세요.")

    base = U.enrich(base_entry, corpmap, dart_key)

    # 관련성 필터 (광범위 섹터는 업종 일치 또는 제품 공통점 필요)
    bsec, bind = (base["sector"] or "").lower(), (base["industry"] or "").lower()

    def relevant(e):
        if e["code"] == base["code"]:
            return False
        same_sector = bsec and e["sector"].lower() == bsec
        same_industry = bind and e["industry"].lower() == bind
        product_hit = scoring._product_overlap(base["mainProducts"], e.get("mainProducts")) > 0
        if same_industry or product_hit:
            return True
        if same_sector and bsec not in BROAD_SECTORS:
            return True
        return False

    cands = [e for e in U.UNIVERSE if relevant(e)]
    # 사전 유사도(메타데이터)로 시장별 상위 압축
    scored = [(e, scoring.similarity(base, e)) for e in cands]
    scored = [x for x in scored if x[1] > 0]

    def top(mkt):
        arr = sorted([x for x in scored if x[0]["market"] == mkt], key=lambda x: -x[1])[:MAX_PER_MARKET]
        return [e for e, _ in arr]

    members = top("KOSPI") + top("KOSDAQ")
    enriched = []
    total = max(1, len(members))
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, c in enumerate(ex.map(lambda e: U.enrich(e, corpmap, dart_key), members)):
            enriched.append(c)
            if progress:
                progress((i + 1) / total)

    peer = {"per": _avg([c["per"] for c in enriched]), "eps": _avg([c["eps"] for c in enriched])}
    for c in enriched:
        c["similarityScore"] = scoring.similarity(base, c)
        vs, reason = scoring.score_valuation(c, peer)
        c["valuationScore"] = vs if c["financials"] != "missing" else 0
        c["qualityScore"] = scoring.quality_score(c)
        c["finalScore"] = round(c["similarityScore"] * 0.40 + c["valuationScore"] * 0.45 + c["qualityScore"] * 0.15)
        c["reason"] = "재무 데이터 없음(계산 불가)" if c["financials"] == "missing" else reason

    def rank(mkt):
        arr = sorted([c for c in enriched if c["market"] == mkt], key=lambda c: -c["finalScore"])[:10]
        for i, c in enumerate(arr):
            c["rank"] = i + 1
        return arr

    return {"base": base, "kospi": rank("KOSPI"), "kosdaq": rank("KOSDAQ"), "peer": peer}
