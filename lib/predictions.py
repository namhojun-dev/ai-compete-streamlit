"""예측 저널 + 캘리브레이션 — '분석 주체의 승률'을 베이지안 관점으로 누적·측정.

핵심: 개별 이벤트가 아니라 반복적 분석 행위를 로깅해 주체/시나리오별 승률과
캘리브레이션(확률이 실제로 맞는지)을 계산한다.
"""
from __future__ import annotations
import json
import os
import threading
from datetime import date

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRED_FILE = os.path.join(_DIR, "data", "predictions.json")
_lock = threading.Lock()

SCENARIOS = ["실적 기반", "매크로/이벤트", "기술적 돌파", "밸류에이션", "수급/심리", "기타"]
FIELDS = ["id", "date", "asset", "subject", "prob", "scenario", "logic",
          "horizon", "entry", "note", "outcome", "result_note"]


def load() -> list[dict]:
    with _lock:
        if not os.path.exists(PRED_FILE):
            return []
        try:
            with open(PRED_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []


def _save(rows: list[dict]):
    with _lock:
        with open(PRED_FILE, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)


def add(asset, subject, prob, scenario, logic="", horizon=20,
        entry=None, note="", pred_date=None) -> dict:
    rows = load()
    nid = (max((r["id"] for r in rows), default=0) + 1)
    row = {"id": nid, "date": pred_date or date.today().isoformat(),
           "asset": asset.strip(), "subject": (subject or "나").strip(),
           "prob": int(prob), "scenario": scenario, "logic": logic.strip(),
           "horizon": int(horizon), "entry": entry, "note": note.strip(),
           "outcome": None, "result_note": ""}
    rows.append(row)
    _save(rows)
    return row


def resolve(pred_id: int, outcome, result_note=""):
    """outcome: 1(상승) / 0(하락) / None(미정)."""
    rows = load()
    for r in rows:
        if r["id"] == pred_id:
            r["outcome"] = outcome
            r["result_note"] = result_note
            break
    _save(rows)


def delete(pred_id: int):
    _save([r for r in load() if r["id"] != pred_id])


def replace_all(rows: list[dict]):
    """CSV 복원 등 전체 교체."""
    norm = []
    for r in rows:
        norm.append({k: r.get(k) for k in FIELDS})
    _save(norm)


# ---------- 지표 ----------
def _resolved(rows):
    return [r for r in rows if r.get("outcome") in (0, 1) and r.get("prob") is not None]


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def metrics(rows: list[dict]) -> dict:
    res = _resolved(rows)
    n = len(res)
    if not n:
        return {"n": 0, "open": len([r for r in rows if r.get("outcome") not in (0, 1)])}
    # Brier: 확률(0~1)과 실제(0/1)의 제곱오차 평균 — 낮을수록 잘 보정됨
    brier = _mean([((r["prob"] / 100) - r["outcome"]) ** 2 for r in res])
    # 적중: 확률>=50을 '상승 예측'으로 보고 실제와 일치율
    hit = _mean([1 if (r["prob"] >= 50) == (r["outcome"] == 1) else 0 for r in res])
    # 로그손실
    import math
    ll = _mean([-(r["outcome"] * math.log(max(min(r["prob"] / 100, 0.999), 0.001))
                  + (1 - r["outcome"]) * math.log(max(min(1 - r["prob"] / 100, 0.999), 0.001)))
                for r in res])
    avg_prob = _mean([r["prob"] for r in res])
    actual_up = _mean([r["outcome"] for r in res]) * 100
    return {"n": n, "open": len([r for r in rows if r.get("outcome") not in (0, 1)]),
            "brier": brier, "hit": hit * 100, "logloss": ll,
            "avg_prob": avg_prob, "actual_up": actual_up}


def calibration(rows, bins=5) -> list[dict]:
    """확률 구간별 예측확률 평균 vs 실제 상승률 — 대각선에 가까울수록 잘 보정."""
    res = _resolved(rows)
    out = []
    width = 100 / bins
    for b in range(bins):
        lo, hi = b * width, (b + 1) * width
        grp = [r for r in res if (lo <= r["prob"] < hi) or (b == bins - 1 and r["prob"] == 100)]
        if not grp:
            continue
        out.append({"구간": f"{int(lo)}-{int(hi)}%", "건수": len(grp),
                    "평균예측": round(_mean([r["prob"] for r in grp]), 1),
                    "실제상승률": round(_mean([r["outcome"] for r in grp]) * 100, 1)})
    return out


def by_group(rows, key) -> list[dict]:
    """주체/시나리오별 승률·Brier·건수."""
    res = _resolved(rows)
    groups = {}
    for r in res:
        groups.setdefault(r.get(key) or "(미지정)", []).append(r)
    out = []
    for g, grp in groups.items():
        hit = _mean([1 if (r["prob"] >= 50) == (r["outcome"] == 1) else 0 for r in grp]) * 100
        brier = _mean([((r["prob"] / 100) - r["outcome"]) ** 2 for r in grp])
        out.append({key: g, "건수": len(grp), "적중률": round(hit, 1),
                    "Brier": round(brier, 3), "평균확률": round(_mean([r["prob"] for r in grp]), 1)})
    return sorted(out, key=lambda x: -x["건수"])
