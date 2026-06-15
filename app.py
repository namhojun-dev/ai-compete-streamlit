"""AI Compete — 국내 밸류에이션 & 13F 대시보드 (Streamlit)."""
import os
import pandas as pd
import streamlit as st

from lib import dart, screener, comparables, thirteenf, us_screener
from lib import universe as U

st.set_page_config(page_title="AI Compete — 밸류에이션·13F", page_icon="📊", layout="wide")

def _secret(key: str, default: str = "") -> str:
    """secrets.toml 이 없으면 st.secrets 접근이 예외를 던지므로 env 로 폴백."""
    try:
        val = st.secrets[key]
        if val:
            return val
    except Exception:
        pass
    return os.environ.get(key, default)


DART_KEY = _secret("DART_API_KEY")
OPENFIGI_KEY = _secret("OPENFIGI_API_KEY")


@st.cache_resource(show_spinner=False)
def corpmap():
    return dart.download_corpcode_map(DART_KEY)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_sector(sector):
    return screener.sector_screen(sector, corpmap(), DART_KEY)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_industry(industry):
    return screener.industry_screen(industry, corpmap(), DART_KEY)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_comparables(q):
    return comparables.get_comparables(q, corpmap(), DART_KEY)


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def cached_13f(cik):
    return thirteenf.get_13f(cik, OPENFIGI_KEY)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_us(sector):
    return us_screener.screen_us(sector)


# ---------- 포맷 헬퍼 ----------
def f1(n):
    return "—" if n is None else f"{n:.1f}"


def won(n):
    return "—" if n is None else f"{round(n):,}"


def pct(n):
    return "—" if n is None else f"{n:.1f}%"


def usd(n):
    if n is None:
        return "—"
    if n >= 1e12:
        return f"${n/1e12:.2f}T"
    if n >= 1e9:
        return f"${n/1e9:.2f}B"
    if n >= 1e6:
        return f"${n/1e6:.1f}M"
    return f"${round(n):,}"


def usd2(n):
    return "—" if n is None else f"${n:,.2f}"


st.title("📊 AI Compete — 한국·미국 밸류에이션 · 13F")
st.caption("한국(DART) · 미국(Yahoo) 저평가 스크리너 · 유사 종목 비교 · 미국 기관 13F 보유 (투자 자문 아님)")

if not DART_KEY:
    st.warning("DART_API_KEY 가 설정되지 않아 PER·EPS·ROE 등 국내 재무가 비어 보일 수 있습니다. "
               "Streamlit Cloud → Settings → Secrets 에 `DART_API_KEY` 를 추가하세요.")

tab1, tab2, tab4, tab3 = st.tabs(
    ["🔎 한국 저평가 스크리너", "🆚 유사 종목 비교", "🇺🇸 미국 저평가 스크리너", "🏦 13F 기관 보유"])

# ===== 탭 1: 스크리너 =====
with tab1:
    sectors = U.get_sectors()
    labels = {s["label"]: s for s in sectors}
    csel = st.columns([2, 2, 1.4, 1.6])
    sec_label = csel[0].selectbox("섹터", list(labels.keys()))
    sec = labels[sec_label]
    ind_opts = ["전체 섹터"] + [i["label"] for i in sec["industries"]]
    ind_label = csel[1].selectbox("업종", ind_opts)
    market = csel[2].radio("시장", ["전체", "KOSPI", "KOSDAQ"], horizontal=True)
    sort_key = csel[3].radio("정렬", ["저평가점수", "PER↓", "ROE↑", "PBR↓"], horizontal=True)

    with st.spinner("DART 재무 조회 + 저평가 점수 계산 중… (첫 조회 10~40초, 이후 캐시)"):
        if ind_label == "전체 섹터":
            res = cached_sector(sec["sector"])
        else:
            ind = next(i["industry"] for i in sec["industries"] if i["label"] == ind_label)
            res = cached_industry(ind)

    rows = [r for r in res["rows"] if market == "전체" or r["market"] == market]

    def sval(c):
        if sort_key == "PER↓":
            return (c["per"] if (c["per"] and c["per"] > 0) else float("inf"),)
        if sort_key == "ROE↑":
            return (-(c["roe"] if c["roe"] is not None else -1e9),)
        if sort_key == "PBR↓":
            return (c["pbr"] if (c["pbr"] and c["pbr"] > 0) else float("inf"),)
        return (-c["valuationScore"], -c["qualityScore"])

    rows = sorted(rows, key=sval)
    df = pd.DataFrame([{
        "순위": i + 1, "종목": c["name"], "티커": c["code"], "시장": c["market"],
        "업종": U.industry_label(c["industry"]), "현재가": won(c["price"]),
        "PER": f1(c["per"]), "EPS": won(c["eps"]), "PBR": f1(c["pbr"]),
        "ROE": pct(c["roe"]), "영업이익률": pct(c["operatingMargin"]),
        "저평가점수": ("계산불가" if c["financials"] == "missing" else c["valuationScore"]),
        "의견": c["reason"],
    } for i, c in enumerate(rows)])
    st.markdown(f"**{res['label']} · {len(rows)}종목** — {sort_key}")
    st.dataframe(df, hide_index=True, use_container_width=True)
    for w in res.get("warnings", []):
        st.caption("⚠ " + w)

# ===== 탭 2: 유사 종목 =====
with tab2:
    q = st.text_input("종목 코드(예: 005930) 또는 회사명(예: 삼성전자)", "")
    if st.button("비교 분석", type="primary") and q.strip():
        try:
            with st.spinner("유사 종목 탐색 + DART 재무 비교 중…"):
                r = cached_comparables(q.strip())
            b = r["base"]
            peer_per = r["peer"]["per"]
            cols = st.columns(5)
            cols[0].metric("기준 종목", b["name"])
            cols[1].metric("현재가", won(b["price"]))
            cols[2].metric("PER", f1(b["per"]))
            cols[3].metric("동종 평균 PER", f1(peer_per))
            cols[4].metric("ROE", pct(b["roe"]))

            def cmp_df(arr):
                return pd.DataFrame([{
                    "순위": c["rank"], "종목": c["name"], "티커": c["code"], "시장": c["market"],
                    "현재가": won(c["price"]), "PER": f1(c["per"]), "EPS": won(c["eps"]),
                    "PBR": f1(c["pbr"]), "ROE": pct(c["roe"]),
                    "유사도": c["similarityScore"], "저평가": c["valuationScore"], "최종": c["finalScore"],
                    "의견": c["reason"],
                } for c in arr])

            st.markdown("#### 코스피 유사 종목 (최종점수순)")
            st.dataframe(cmp_df(r["kospi"]), hide_index=True, use_container_width=True) if r["kospi"] else st.info("코스피 유사 종목 없음")
            st.markdown("#### 코스닥 유사 종목 (최종점수순)")
            st.dataframe(cmp_df(r["kosdaq"]), hide_index=True, use_container_width=True) if r["kosdaq"] else st.info("코스닥 유사 종목 없음")
            st.caption("최종점수 = 유사도×0.40 + 저평가×0.45 + 퀄리티×0.15 · 숫자는 DART/Yahoo 실데이터")
        except Exception as e:
            st.error(str(e))

# ===== 탭 4: 미국 스크리너 =====
with tab4:
    us_secs = us_screener.us_sectors()
    us_map = {f"{U.sector_label(s)}  ({n})": s for s, n in us_secs}
    uc = st.columns([3, 2])
    us_sec_label = uc[0].selectbox("섹터 (미국)", list(us_map.keys()), key="us_sec")
    us_sort = uc[1].radio("정렬", ["저평가점수", "PER↓", "ROE↑", "PBR↓"], horizontal=True, key="us_sort")
    with st.spinner("Yahoo 재무 조회 + 저평가 점수 계산 중… (첫 조회 5~15초, 이후 캐시)"):
        ures = cached_us(us_map[us_sec_label])
    urows = ures["rows"]

    def usval(c):
        if us_sort == "PER↓":
            return (c["per"] if (c["per"] and c["per"] > 0) else float("inf"),)
        if us_sort == "ROE↑":
            return (-(c["roe"] if c["roe"] is not None else -1e9),)
        if us_sort == "PBR↓":
            return (c["pbr"] if (c["pbr"] and c["pbr"] > 0) else float("inf"),)
        return (-c["valuationScore"], -c["qualityScore"])

    urows = sorted(urows, key=usval)
    udf = pd.DataFrame([{
        "순위": i + 1, "종목": c["name"], "티커": c["symbol"],
        "업종": U.industry_label(c["industry"]), "현재가": usd2(c["price"]),
        "PER": f1(c["per"]), "EPS": usd2(c["eps"]), "PBR": f1(c["pbr"]),
        "ROE": pct(c["roe"]), "영업이익률": pct(c["operatingMargin"]),
        "시총": usd(c["marketCap"]),
        "저평가점수": ("계산불가" if c["financials"] == "missing" else c["valuationScore"]),
        "의견": c["reason"],
    } for i, c in enumerate(urows)])
    st.markdown(f"**{U.sector_label(ures['sector'])} · {len(urows)}종목** — {us_sort}")
    st.dataframe(udf, hide_index=True, use_container_width=True)
    for w in ures.get("warnings", []):
        st.caption("⚠ " + w)
    st.caption("출처 Yahoo Finance · PER/EPS/PBR/ROE 실데이터 · 투자 자문 아님")

# ===== 탭 3: 13F =====
with tab3:
    mgrs = {m["label"]: m["cik"] for m in thirteenf.MANAGERS}
    msel = st.selectbox("기관 선택", list(mgrs.keys()))
    if st.button("보유내역 조회", type="primary"):
        try:
            with st.spinner("SEC EDGAR 13F 조회 + 직전 분기 비교 + 티커 매핑 중…"):
                r = cached_13f(mgrs[msel])
            cols = st.columns(4)
            cols[0].metric("기관", r["manager"])
            cols[1].metric("보고 기준일", r["reportDate"])
            cols[2].metric("포트폴리오", usd(r["totalValue"]))
            cols[3].metric("보유 종목", f"{r['positions']}개")
            badge = {"new": "신규", "add": "추가", "reduce": "축소", "unchanged": "유지"}
            df = pd.DataFrame([{
                "순위": h["rank"], "티커": h["ticker"] or "—", "종목(발행사)": h["issuer"],
                "평가액": usd(h["value"]), "비중": pct(h["pct"]),
                "보유주식": won(h["shares"]),
                "변화": badge.get(h["change"], h["change"]),
                "QoQ": ("NEW" if h["deltaSharesPct"] is None else f"{h['deltaSharesPct']:+.0f}%"),
            } for h in r["holdings"]])
            st.markdown(f"**보유 종목** — 변화는 직전 분기({r['prevReportDate'] or '—'}) 대비")
            st.dataframe(df, hide_index=True, use_container_width=True)
            if r["exited"]:
                st.markdown("**직전 분기 대비 전량 청산**")
                st.write(" · ".join(f"{e['issuer']} ({usd(e['prevValue'])})" for e in r["exited"]))
            st.caption(f"출처 SEC EDGAR · 신고일 {r['filedAt']} · 미국 롱 포지션만, ~45일 지연")
        except Exception as e:
            st.error(str(e))
