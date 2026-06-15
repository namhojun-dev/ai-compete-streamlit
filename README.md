# AI Compete — 국내 밸류에이션 · 13F (Streamlit)

DART 실재무 기반 **섹터/업종 저평가 스크리너**, **유사 종목 PER·EPS 비교**, 미국 기관 **13F 보유내역**을
한 화면에서 보는 Streamlit 대시보드. (Next.js 원본의 데이터 기능을 Python으로 포팅)

## 기능
- 🔎 **섹터 저평가 스크리너** — 섹터/업종 선택 → 종목을 저평가 점수순 정렬, 코스피/코스닥 필터, PER·ROE·PBR 정렬
- 🆚 **유사 종목 비교** — 코드/회사명 입력 → 유사 국내 종목을 코스피/코스닥으로 나눠 정량 점수 순위
- 🏦 **13F 기관 보유** — 버핏·애크먼·버리 등 14곳의 분기 미국주식 보유 + 직전 분기 대비 변화(CUSIP→티커 매핑)

## 로컬 실행
```bash
pip install -r requirements.txt
export DART_API_KEY=...        # OpenDART 무료 키
streamlit run app.py
```

## Streamlit Community Cloud 배포 (무료, 영구 URL)
1. https://share.streamlit.io → GitHub 로그인
2. **New app** → 이 저장소 선택, Main file = `app.py`
3. **Advanced → Secrets** 에 입력:
   ```
   DART_API_KEY = "..."
   OPENFIGI_API_KEY = ""
   ```
4. Deploy → `https://<app>.streamlit.app` 영구 URL

## 데이터 출처
- 시세: Yahoo Finance (키 불필요) · 국내 재무: OpenDART(전자공시) · 13F: SEC EDGAR · 티커 매핑: OpenFIGI
- 모든 숫자는 데이터 소스 실값만 사용, 없으면 "데이터 없음"으로 표시. 투자 자문 아님.
