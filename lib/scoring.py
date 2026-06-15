"""정량 점수 — 저평가/유사도. Next.js scoreValuation.ts / scoreSimilarity.ts 포팅."""
from __future__ import annotations
import re


# ---------- 저평가 점수 ----------
def per_score(per):
    if per is None or per <= 0:
        return 0
    if per < 5: return 90
    if per < 10: return 80
    if per < 15: return 65
    if per < 20: return 50
    if per < 30: return 35
    return 20


def eps_score(eps, peer_eps):
    if eps is None or eps <= 0:
        return 0
    if peer_eps and peer_eps > 0:
        return 80 if eps > peer_eps else 50
    return 50


def roe_score(roe):
    if roe is None: return 0
    if roe < 0: return 0
    if roe < 5: return 30
    if roe < 8: return 50
    if roe < 12: return 70
    if roe < 18: return 85
    return 95


def op_margin_score(m):
    if m is None: return 0
    if m < 0: return 0
    if m < 5: return 40
    if m < 10: return 60
    if m < 15: return 75
    if m < 20: return 85
    return 95


def rev_growth_score(g):
    if g is None: return 0
    if g < 0: return 20
    if g < 5: return 45
    if g < 10: return 65
    if g < 20: return 80
    return 90


def pbr_score(pbr):
    if pbr is None or pbr <= 0: return 0
    if pbr < 1: return 90
    if pbr < 1.5: return 80
    if pbr < 2: return 65
    if pbr < 3: return 50
    if pbr < 5: return 35
    return 20


def quality_score(c) -> int:
    r = roe_score(c.get("roe"))
    o = op_margin_score(c.get("operatingMargin"))
    e = 100 if (c.get("eps") is not None and c["eps"] > 0) else 0
    return round(r * 0.4 + o * 0.4 + e * 0.2)


def score_valuation(c, peer) -> tuple[int, str]:
    per = c.get("per")
    if per is None or per <= 0:
        return (0, "PER 데이터 없음/적자라 저평가 점수 제외" if per is None else "PER 음수(적자)로 제외")
    ps = per_score(per)
    es = eps_score(c.get("eps"), peer.get("eps"))
    rs = roe_score(c.get("roe"))
    os_ = op_margin_score(c.get("operatingMargin"))
    gs = rev_growth_score(c.get("revenueGrowthYoY"))
    bs = pbr_score(c.get("pbr"))
    per_adj = ps
    if peer.get("per") and peer["per"] > 0:
        discount = (peer["per"] - per) / peer["per"]
        per_adj = max(0, min(100, ps + round(discount * 20)))
    score = round(per_adj * 0.3 + es * 0.2 + rs * 0.15 + os_ * 0.15 + gs * 0.1 + bs * 0.1)
    drivers = []
    if per_adj >= 65: drivers.append("PER 부담 낮음")
    elif per_adj <= 35: drivers.append("PER 높은 편")
    if es >= 80: drivers.append("EPS 동종평균 대비 높음")
    if rs >= 70: drivers.append("ROE 양호")
    if os_ >= 75: drivers.append("영업이익률 양호")
    if bs >= 80: drivers.append("PBR 부담 낮음")
    return (score, ", ".join(drivers) if drivers else "지표 중립")


# ---------- 유사도 점수 ----------
def _norm(s):
    return (s or "").strip().lower()


def _product_overlap(a, b):
    a = [x for x in (a or []) if len(x) >= 2]
    b = [_norm(x) for x in (b or []) if len(x) >= 2]
    if not a or not b:
        return 0.0
    hit = 0
    for x in (_norm(x) for x in a):
        for y in b:
            if x == y or (len(x) >= 3 and len(y) >= 3 and (x in y or y in x)):
                hit += 1
                break
    return hit / max(len(a), len(b))


def _tokens(s):
    return {w for w in re.split(r"\s+", re.sub(r"[^a-z0-9가-힣\s]", " ", (s or "").lower())) if len(w) >= 2}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a) + len(b) - inter
    return inter / union if union else 0.0


def similarity(base, cand) -> int:
    sector = 100 if base.get("sector") and _norm(base["sector"]) == _norm(cand.get("sector")) else 0
    industry = 0
    if base.get("industry") and cand.get("industry"):
        if _norm(base["industry"]) == _norm(cand["industry"]):
            industry = 100
        else:
            industry = round(_jaccard(_tokens(base["industry"]), _tokens(cand["industry"])) * 100)
    product = round(_product_overlap(base.get("mainProducts"), cand.get("mainProducts")) * 100)
    kb = _tokens(base.get("businessSummary")) | {t for p in (base.get("mainProducts") or []) for t in _tokens(p)}
    kc = _tokens(cand.get("businessSummary")) | {t for p in (cand.get("mainProducts") or []) for t in _tokens(p)}
    keyword = round(_jaccard(kb, kc) * 100)
    mcap = 0
    a, b = base.get("marketCap"), cand.get("marketCap")
    if a and b and a > 0 and b > 0:
        mcap = round(min(a, b) / max(a, b) * 100)
    fin = 0
    if base.get("operatingMargin") is not None and cand.get("operatingMargin") is not None:
        diff = abs(base["operatingMargin"] - cand["operatingMargin"])
        fin = max(0, round((1 - min(diff, 30) / 30) * 100))
    return round(sector * 0.25 + industry * 0.20 + product * 0.20 + keyword * 0.15 + mcap * 0.10 + fin * 0.10)
