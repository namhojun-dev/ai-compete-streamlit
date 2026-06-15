"""멀티 LLM 토론 — GPT·Gemini·Claude 3라운드 토론 + Perplexity 종합. Next.js orchestrator 포팅."""
from __future__ import annotations
import os
from concurrent.futures import ThreadPoolExecutor

import requests
from . import debate_parse as P

GPT_MODEL = "gpt-5.4"
GEMINI_MODEL = "gemini-2.5-pro"
CLAUDE_MODEL = "claude-opus-4-8"
PPLX_MODEL = "sonar-reasoning-pro"
MODELS = ["gpt", "gemini", "claude"]
DISPLAY = {"gpt": "GPT (OpenAI)", "gemini": "Gemini (Google)", "claude": "Claude (Anthropic)"}

COMMON_INSTRUCTIONS = """당신은 미국 주식 시장의 베테랑 트레이더이자 펀더멘털·기술적 분석 전문가입니다.
사용자가 제공한 종목에 대해 "지금 이 시점"에 어떤 포지션(롱/숏/관망)을 잡을지 의견을 제시해야 합니다.

규칙:
1. 모든 응답은 반드시 한국어로 작성하세요. 고유명사는 영문 병기 가능.
2. 분석에는 펀더멘털(실적/가이던스/밸류에이션), 기술적(추세/지지·저항), 매크로/섹터, 단기 카탈리스트, 리스크를 포함.
3. 의견은 명확히: "롱"/"숏"/"관망" 중 하나 + 신뢰도(0-100) + 강도(-100 강한 숏 ~ +100 강한 롱).
4. 본문은 GitHub Flavored Markdown(헤더 ##, 불릿, 굵게, 표)으로 가독성 있게. 분량 500~1000자.
5. 출력 형식을 반드시 따르세요:

[자유 서술 본문 — Markdown]

---JSON---
{
  "position": "롱" | "숏" | "관망",
  "confidence": 0~100 정수,
  "strength": -100~100 정수,
  "target_price": 숫자 또는 null,
  "stop_loss": 숫자 또는 null,
  "key_reasons": ["근거1", "근거2", "근거3"]
}

---JSON--- 구분자와 그 뒤 유효한 JSON을 절대 누락하지 마세요."""

PPLX_SYSTEM = """당신은 여러 AI 분석가의 토론을 종합하는 시니어 리서치 애널리스트입니다.
GPT, Gemini, Claude 세 AI가 동일 종목에 대해 3라운드 토론을 마쳤습니다.

임무: 1) 실시간 웹 검색으로 토론에서 빠진 최신 정보(오늘자 뉴스/가격/실적 일정) 보완,
2) 세 AI 최종 의견의 합의/대립 정리, 3) 실행 가능한 종합 의견 + 가격 가이드 제시.

출력: 마크다운 보고서 쓰지 말고 모든 정보를 JSON 필드에 담으세요. 응답 마지막에 ---JSON--- 뒤 JSON:
---JSON---
{
  "summary": "핵심 결론 평문 150~280자(마크다운/줄바꿈 금지)",
  "consensus": "롱" | "숏" | "관망",
  "target_price": 숫자 또는 null,
  "stop_loss": 숫자 또는 null,
  "entry_zone": "진입 구간 텍스트 또는 null",
  "notable_disagreements": ["모델 간 대립 한 줄", "..."],
  "fresh_insights": ["웹검색으로 얻은 최신 사실 한 줄(숫자/날짜 포함)", "..."],
  "citations": [{"title": "출처", "url": "https://..."}],
  "warning": "유의사항 한 줄(선택)"
}
target_price/stop_loss는 가능한 한 구체 숫자로(세 AI 중 하나라도 숫자를 냈으면 종합 도출)."""


def _quote_block(ticker, quote):
    if quote and quote.get("price") is not None:
        cp = quote.get("changePercent")
        cap = quote.get("marketCap")
        return (f"현재 시세(참고):\n- 종목: {quote.get('shortName') or ticker} ({quote.get('symbol', ticker)})\n"
                f"- 현재가: ${quote['price']:.2f}" + (f" ({cp:+.2f}%)" if cp is not None else "") + "\n"
                + (f"- 시가총액: ${cap/1e9:.2f}B\n" if cap else ""))
    return "(시세를 가져오지 못했습니다. 보유 지식으로 분석하세요.)"


def build_round1(ticker, quote):
    return (f"**1차 라운드 (독립 의견)**\n\n다음 미국 주식에 대해 현재 시점의 포지션 분석을 제시하세요.\n\n"
            f"종목: **{ticker}**\n\n{_quote_block(ticker, quote)}\n\n"
            "다른 모델 의견을 보지 않은 상태에서 본인만의 독립적 분석을 작성하세요.")


def _fmt_prior(op):
    tp = f"${op['target_price']}" if op.get("target_price") else "제시 안함"
    sl = f"${op['stop_loss']}" if op.get("stop_loss") else "제시 안함"
    return (f"### {DISPLAY[op['modelId']]} — {op['round']}차\n"
            f"- 포지션: **{op['position']}** | 신뢰도 {op['confidence']}% | 강도 {op['strength']}\n"
            f"- 목표가 {tp} / 손절 {sl}\n- 핵심 근거: {' / '.join(op['key_reasons'])}\n\n"
            f"분석 요지:\n{op['body'][:1000]}")


def build_round2(ticker, quote, self_model, own_r1, others_r1):
    others = "\n---\n\n".join(_fmt_prior(o) for o in others_r1)
    return (f"**2차 라운드 (반박/동의/보완)**\n\n종목: **{ticker}**\n\n"
            f"당신({DISPLAY[self_model]})의 1차: {own_r1['position']} | 신뢰도 {own_r1['confidence']}% | 강도 {own_r1['strength']}\n\n"
            f"다른 모델의 1차 의견:\n\n{others}\n\n"
            "위 의견을 검토해 2차 의견을 작성하세요: 동의/반박 지점과 근거, 놓친 관점, 입장 변경 시 사유.")


def build_round3(ticker, self_model, own_r1, own_r2, others_r2):
    others = "\n---\n\n".join(_fmt_prior(o) for o in others_r2)
    return (f"**3차 라운드 (최종 입장)**\n\n종목: **{ticker}**\n\n"
            f"당신({DISPLAY[self_model]}) 변천: 1차 {own_r1['position']}(강도 {own_r1['strength']}) → "
            f"2차 {own_r2['position']}(강도 {own_r2['strength']})\n\n다른 모델 2차 의견:\n\n{others}\n\n"
            "마지막 라운드입니다. 모든 토론을 종합해 최종 포지션을 확정하고, 신뢰도·목표가·손절가를 "
            "가장 자신 있는 수치로 제시하세요. 본문은 최종 논리를 200~400자로 간결히.")


def build_pplx_prompt(ticker, quote, finals):
    blocks = "\n\n---\n\n".join(
        f"## {DISPLAY[op['modelId']]} 최종\n- 포지션 **{op['position']}** | 신뢰도 {op['confidence']}% | 강도 {op['strength']}\n"
        f"- 목표가 {('$'+str(op['target_price'])) if op.get('target_price') else 'N/A'} / 손절 "
        f"{('$'+str(op['stop_loss'])) if op.get('stop_loss') else 'N/A'}\n- 근거: {' / '.join(op['key_reasons'])}\n\n{op['body']}"
        for op in finals)
    q = f" 현재가 ${quote['price']:.2f}" if quote and quote.get("price") is not None else ""
    return (f"종목: **{ticker}**{q}\n\n세 AI의 최종 의견을 토대로 실시간 웹 검색으로 최신 정보를 보강해 "
            f"사용자에게 전달할 종합 분석을 작성하세요.\n\n{blocks}")


# ---------- 모델 호출 ----------
def _err(model_id, rnd, msg):
    return {"modelId": model_id, "round": rnd, "position": "관망", "confidence": 0, "strength": 0,
            "target_price": None, "stop_loss": None, "key_reasons": [f"오류: {msg}"],
            "body": f"{model_id} 호출 실패: {msg}"}


def _call_gpt(prompt):
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    r = client.responses.create(model=GPT_MODEL, instructions=COMMON_INSTRUCTIONS, input=prompt)
    return P.parse_opinion(r.output_text)


def _call_gemini(prompt):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GOOGLE_GENERATIVE_AI_API_KEY"])
    r = client.models.generate_content(
        model=GEMINI_MODEL, contents=prompt,
        config=types.GenerateContentConfig(system_instruction=COMMON_INSTRUCTIONS))
    return P.parse_opinion(r.text)


def _call_claude(prompt):
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    kwargs = dict(model=CLAUDE_MODEL, max_tokens=6000, system=COMMON_INSTRUCTIONS,
                  messages=[{"role": "user", "content": prompt}])
    try:
        resp = client.messages.create(thinking={"type": "adaptive"}, **kwargs)
    except Exception:
        resp = client.messages.create(**kwargs)
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    return P.parse_opinion(text)


_CALLERS = {"gpt": _call_gpt, "gemini": _call_gemini, "claude": _call_claude}


def _call(model_id, prompt, rnd):
    try:
        op = _CALLERS[model_id](prompt)
        return {**op, "modelId": model_id, "round": rnd}
    except Exception as e:
        return _err(model_id, rnd, str(e)[:200])


def call_perplexity(prompt):
    key = os.environ.get("PERPLEXITY_API_KEY")
    if not key:
        raise RuntimeError("PERPLEXITY_API_KEY 없음")
    res = requests.post("https://api.perplexity.ai/chat/completions",
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json={"model": PPLX_MODEL, "temperature": 0.3, "stream": False,
                              "messages": [{"role": "system", "content": PPLX_SYSTEM},
                                           {"role": "user", "content": prompt}]}, timeout=120)
    if res.status_code != 200:
        raise RuntimeError(f"Perplexity {res.status_code}: {res.text[:200]}")
    data = res.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    parsed = P.parse_synthesis(content)
    if data.get("citations") and not parsed["citations"]:
        parsed["citations"] = [{"title": u.split("/")[2] if "/" in u else u, "url": u}
                               for u in data["citations"][:12]]
    return parsed


def run_debate(ticker, quote=None, emit=None) -> dict:
    """3라운드 토론 + 종합. emit(stage:str) 콜백으로 진행 알림."""
    def _emit(s):
        if emit:
            emit(s)

    _emit("1차 라운드 — 독립 의견")
    r1p = build_round1(ticker, quote)
    with ThreadPoolExecutor(max_workers=3) as ex:
        r1 = list(ex.map(lambda m: _call(m, r1p, 1), MODELS))

    _emit("2차 라운드 — 반박·보완")
    def r2task(m):
        own = next(o for o in r1 if o["modelId"] == m)
        others = [o for o in r1 if o["modelId"] != m]
        return _call(m, build_round2(ticker, quote, m, own, others), 2)
    with ThreadPoolExecutor(max_workers=3) as ex:
        r2 = list(ex.map(r2task, MODELS))

    _emit("3차 라운드 — 최종 입장")
    def r3task(m):
        o1 = next(o for o in r1 if o["modelId"] == m)
        o2 = next(o for o in r2 if o["modelId"] == m)
        others = [o for o in r2 if o["modelId"] != m]
        return _call(m, build_round3(ticker, m, o1, o2, others), 3)
    with ThreadPoolExecutor(max_workers=3) as ex:
        r3 = list(ex.map(r3task, MODELS))

    _emit("Perplexity 종합 — 웹검색 보강")
    synthesis, synth_err = None, None
    try:
        synthesis = call_perplexity(build_pplx_prompt(ticker, quote, r3))
    except Exception as e:
        synth_err = str(e)[:200]

    return {"ticker": ticker, "quote": quote, "rounds": {1: r1, 2: r2, 3: r3},
            "finals": r3, "synthesis": synthesis, "synthesis_error": synth_err}


def position_to_prob(op) -> int:
    """포지션/강도 → P(상승) % 매핑 (예측 저널 기록용). 강도 -100..100 → 0..100."""
    return int(max(0, min(100, round(50 + op.get("strength", 0) / 2))))
