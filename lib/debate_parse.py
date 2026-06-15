"""토론 응답 파싱 — Next.js parse.ts 포팅. ---JSON--- 구분자 뒤 JSON 추출."""
from __future__ import annotations
import json
import re

SEP = "---JSON---"


def _strip_think(text: str) -> str:
    return re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I).strip()


def _balanced_json(text: str, start_at: int = 0):
    start = text.find("{", start_at)
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if esc:
            esc = False
            continue
        if in_str:
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _extract_json(text: str):
    cleaned = _strip_think(text)
    idx = cleaned.rfind(SEP)
    if idx != -1:
        after = cleaned[idx + len(SEP):]
        obj = _balanced_json(after)
        if obj:
            return cleaned[:idx].strip(), obj
    fence = re.search(r"```json\s*([\s\S]*?)```", cleaned, re.I)
    if fence:
        obj = _balanced_json(fence.group(1))
        if obj:
            return cleaned.replace(fence.group(0), "").strip(), obj
    # 마지막 수단: 가장 긴 balanced 객체
    best, best_start, pos = None, -1, 0
    while pos < len(cleaned):
        obj = _balanced_json(cleaned, pos)
        if not obj:
            break
        if best is None or len(obj) > len(best):
            best, best_start = obj, cleaned.find(obj, pos)
        pos = cleaned.find(obj, pos) + len(obj)
    if best:
        return cleaned[:best_start].strip(), best
    return cleaned, None


def _try_json(s: str) -> dict:
    try:
        return json.loads(s)
    except Exception:
        repaired = re.sub(r",\s*([}\]])", r"\1", s).replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
        try:
            return json.loads(repaired)
        except Exception:
            return {}


def _clamp(n, lo, hi):
    try:
        return max(lo, min(hi, float(n)))
    except (TypeError, ValueError):
        return lo


def _position(p) -> str:
    s = str(p or "").strip().lower()
    if s in ("롱", "long", "buy"):
        return "롱"
    if s in ("숏", "short", "sell"):
        return "숏"
    return "관망"


def parse_opinion(text: str) -> dict:
    body, js = _extract_json(text)
    p = _try_json(js) if js else {}
    position = _position(p.get("position"))
    conf = _clamp(p.get("confidence", 50), 0, 100)
    try:
        strength = float(p.get("strength"))
    except (TypeError, ValueError):
        strength = 50 if position == "롱" else (-50 if position == "숏" else 0)
    strength = _clamp(strength, -100, 100)
    tp = p.get("target_price")
    sl = p.get("stop_loss")
    reasons = [str(r) for r in p.get("key_reasons", [])][:6] if isinstance(p.get("key_reasons"), list) else []
    return {"position": position, "confidence": round(conf), "strength": round(strength),
            "target_price": float(tp) if isinstance(tp, (int, float)) else None,
            "stop_loss": float(sl) if isinstance(sl, (int, float)) else None,
            "key_reasons": reasons, "body": body or _strip_think(text).strip()}


def parse_synthesis(text: str) -> dict:
    body, js = _extract_json(text)
    p = _try_json(js) if js else {}
    summary = (str(p.get("summary")).strip() if p.get("summary") else "") or body[:280] or "[종합 요약 파싱 실패]"
    tp, sl = p.get("target_price"), p.get("stop_loss")
    cites = []
    for c in (p.get("citations") or [])[:12]:
        if isinstance(c, dict) and c.get("url"):
            cites.append({"title": str(c.get("title", "")), "url": str(c["url"])})
        elif isinstance(c, str):
            cites.append({"title": c, "url": c})
    return {"summary": summary, "consensus": _position(p.get("consensus")),
            "target_price": float(tp) if isinstance(tp, (int, float)) else None,
            "stop_loss": float(sl) if isinstance(sl, (int, float)) else None,
            "entry_zone": str(p["entry_zone"]).strip() if p.get("entry_zone") else None,
            "notable_disagreements": [str(x) for x in (p.get("notable_disagreements") or [])][:8],
            "fresh_insights": [str(x) for x in (p.get("fresh_insights") or [])][:8],
            "citations": cites,
            "warning": str(p["warning"]) if p.get("warning") else None}
