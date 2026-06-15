"""OpenDART(전자공시) 연동 — corpCode 매핑 + 사업보고서 재무 추출.
Next.js 버전(src/lib/comparables/dart.ts)을 Python으로 포팅."""
from __future__ import annotations
import io
import re
import zipfile
import requests

TIMEOUT = 12


def download_corpcode_map(api_key: str) -> dict[str, str]:
    """종목코드(6자리) -> DART corp_code 매핑. corpCode.xml(zip) 다운로드·파싱."""
    if not api_key:
        return {}
    try:
        r = requests.get(
            "https://opendart.fss.or.kr/api/corpCode.xml",
            params={"crtfc_key": api_key},
            timeout=20,
        )
        if r.status_code != 200 or r.content[:2] != b"PK":
            return {}
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        name = next((n for n in zf.namelist() if n.lower().endswith(".xml")), None)
        if not name:
            return {}
        xml = zf.read(name).decode("utf-8")
    except Exception:
        return {}
    out: dict[str, str] = {}
    for block in re.findall(r"<list>(.*?)</list>", xml, re.S):
        corp = re.search(r"<corp_code>([^<]*)</corp_code>", block)
        stock = re.search(r"<stock_code>([^<]*)</stock_code>", block)
        if corp and stock and re.fullmatch(r"\d{6}", stock.group(1).strip()):
            out[stock.group(1).strip()] = corp.group(1).strip()
    return out


def _num(s):
    if s is None or s == "":
        return None
    try:
        v = float(str(s).replace(",", ""))
        return v
    except ValueError:
        return None


def _clean(s: str) -> str:
    return re.sub(r"\s", "", s or "")


def _by_id(rows, ids, sj):
    for a in rows:
        if a.get("sj_div") in sj and a.get("account_id") in ids:
            return a
    return None


def _by_exact(rows, names, sj):
    nset = {_clean(n) for n in names}
    for a in rows:
        if a.get("sj_div") in sj and _clean(a.get("account_nm", "")) in nset:
            return a
    return None


def _amount(rows, ids, names, sj):
    hit = _by_id(rows, ids, sj) or _by_exact(rows, names, sj)
    if not hit:
        return (None, None)
    return (_num(hit.get("thstrm_amount")), _num(hit.get("frmtrm_amount")))


def _extract_basic_eps(rows):
    """기본 보통주 주당이익. 변형(이익/순이익/손익, '기본 및 희석') + 우선주/희석/계속·중단 구분."""
    is_rows = [a for a in rows if a.get("sj_div") in ("IS", "CIS")]

    def is_basic_common(a):
        nm = _clean(a.get("account_nm", ""))
        if "우선주" in nm:
            return False
        if not re.search(r"주당(순)?(이익|손익|손실)", nm):
            return False
        has_basic = "기본" in nm
        diluted_only = ("희석" in nm) and not has_basic
        return has_basic and not diluted_only

    def prefer_common(arr):
        for a in arr:
            if "보통주" in _clean(a.get("account_nm", "")):
                return a
        return arr[0] if arr else None

    combined = [a for a in is_rows if is_basic_common(a) and not re.search(r"계속영업|중단영업", _clean(a.get("account_nm", "")))]
    if combined:
        return _num(prefer_common(combined).get("thstrm_amount"))
    cont = prefer_common([a for a in is_rows if is_basic_common(a) and "계속영업" in _clean(a.get("account_nm", ""))])
    disc = prefer_common([a for a in is_rows if is_basic_common(a) and "중단영업" in _clean(a.get("account_nm", ""))])
    c = _num(cont.get("thstrm_amount")) if cont else None
    d = _num(disc.get("thstrm_amount")) if disc else None
    if c is None and d is None:
        return None
    return (c or 0) + (d or 0)


def get_dart_metrics(corp_code: str, api_key: str) -> dict | None:
    """최근 사업보고서(연결 우선)에서 재무 추출 → PER/ROE/마진/성장률 계산용 원자료."""
    if not corp_code or not api_key:
        return None
    for year in (2024, 2023):
        for fs_div in ("CFS", "OFS"):
            try:
                r = requests.get(
                    "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                    params={"crtfc_key": api_key, "corp_code": corp_code,
                            "bsns_year": str(year), "reprt_code": "11011", "fs_div": fs_div},
                    timeout=TIMEOUT,
                )
                data = r.json()
            except Exception:
                continue
            if data.get("status") != "000" or not data.get("list"):
                continue
            rows = data["list"]
            rev, prev_rev = _amount(rows, ["ifrs-full_Revenue", "dart_OperatingRevenue"],
                                    ["매출액", "수익(매출액)", "영업수익", "매출"], ["IS", "CIS"])
            op = _amount(rows, ["dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"],
                         ["영업이익", "영업이익(손실)"], ["IS", "CIS"])[0]
            ni = _amount(rows, ["ifrs-full_ProfitLoss"],
                         ["당기순이익", "당기순이익(손실)", "연결당기순이익"], ["IS", "CIS"])[0]
            equity = _amount(rows, ["ifrs-full_Equity"], ["자본총계"], ["BS"])[0]
            eps = _extract_basic_eps(rows)
            # 매출 없어도(은행 등) EPS/순이익/자본 중 하나라도 있으면 채택
            if eps is None and ni is None and equity is None:
                continue
            has_rev = rev is not None and rev != 0
            growth = ((rev - prev_rev) / abs(prev_rev) * 100) if (has_rev and prev_rev not in (None, 0)) else None
            roe = (ni / equity * 100) if (ni is not None and equity not in (None, 0)) else None
            op_margin = (op / rev * 100) if (has_rev and op is not None) else None
            net_margin = (ni / rev * 100) if (has_rev and ni is not None) else None
            bps = None
            if eps and eps > 0 and ni and ni > 0 and equity:
                shares = ni / eps
                if shares > 0:
                    bps = equity / shares
            return {"eps": eps, "revenue": rev, "operatingIncome": op, "netIncome": ni,
                    "equity": equity, "bps": bps, "revenueGrowthYoY": growth, "roe": roe,
                    "operatingMargin": op_margin, "netMargin": net_margin, "year": year, "fsDiv": fs_div}
    return None
