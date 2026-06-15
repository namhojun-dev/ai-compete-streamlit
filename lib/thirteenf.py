"""13F 기관 보유내역 — SEC EDGAR 13F-HR 파싱 + 직전 분기 비교 + OpenFIGI 티커 매핑."""
from __future__ import annotations
import json
import os
import re
import requests

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(_DIR, "data", "managers.json"), encoding="utf-8") as f:
    MANAGERS = json.load(f)

UA = os.environ.get("SEC_USER_AGENT") or "ai-compete-streamlit research contact@example.com"
HEADERS = {"User-Agent": UA, "Accept": "application/json, */*"}


def _get(url, as_json=True):
    r = requests.get(url, headers=HEADERS, timeout=12)
    r.raise_for_status()
    return r.json() if as_json else r.text


def get_recent_13f(cik: str) -> list[dict]:
    c = str(int(cik)).zfill(10)
    d = _get(f"https://data.sec.gov/submissions/CIK{c}.json")
    f = d["filings"]["recent"]
    out = []
    for i, form in enumerate(f["form"]):
        if form == "13F-HR":
            out.append({"accession": f["accessionNumber"][i].replace("-", ""),
                        "reportDate": f["reportDate"][i], "filedAt": f["filingDate"][i]})
    return out


def _tag(block, name):
    m = re.search(rf"<(?:\w+:)?{name}>([^<]*)</(?:\w+:)?{name}>", block)
    return m.group(1).strip() if m else None


def fetch_infotable(cik: str, accession: str) -> list[dict]:
    cik_num = str(int(cik))
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession}"
    idx = _get(f"{base}/index.json")
    names = [it["name"] for it in idx.get("directory", {}).get("item", [])]
    xml_name = next((n for n in names if n.lower().endswith(".xml") and n.lower() != "primary_doc.xml"), None)
    if not xml_name:
        return []
    xml = _get(f"{base}/{xml_name}", as_json=False)
    out = []
    for block in re.findall(r"<(?:\w+:)?infoTable>(.*?)</(?:\w+:)?infoTable>", xml, re.S):
        val = _tag(block, "value")
        ssh = re.search(r"<(?:\w+:)?sshPrnamt>([^<]*)<", block)
        try:
            value = float(val) if val else 0.0
        except ValueError:
            value = 0.0
        out.append({
            "issuer": _tag(block, "nameOfIssuer") or "(unknown)",
            "cusip": (_tag(block, "cusip") or "").upper(),
            "titleOfClass": _tag(block, "titleOfClass") or "",
            "putCall": _tag(block, "putCall"),
            "value": value,
            "shares": float(ssh.group(1)) if ssh and ssh.group(1) else 0.0,
        })
    return out


def _aggregate(rows):
    agg = {}
    for r in rows:
        key = f"{r['cusip']}|{r['titleOfClass']}|{r['putCall'] or ''}"
        if key in agg:
            agg[key]["value"] += r["value"]
            agg[key]["shares"] += r["shares"]
        else:
            agg[key] = dict(r)
    return agg


def _classify(shares, prev):
    if prev is None or prev == 0:
        return "new"
    if shares > prev * 1.01:
        return "add"
    if shares < prev * 0.99:
        return "reduce"
    return "unchanged"


def resolve_tickers(cusips: list[str], api_key: str = "") -> dict:
    """OpenFIGI CUSIP→티커. 무료 한도 고려해 상위 150개·배치 10."""
    seen, uniq = set(), []
    for c in cusips:
        cc = (c or "").upper()
        if re.fullmatch(r"[A-Z0-9]{9}", cc) and cc not in seen:
            seen.add(cc)
            uniq.append(cc)
    out = {}
    batch = 100 if api_key else 10
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key
    for i in range(0, min(len(uniq), 150), batch):
        chunk = uniq[i:i + batch]
        try:
            r = requests.post("https://api.openfigi.com/v3/mapping", headers=headers,
                              json=[{"idType": "ID_CUSIP", "idValue": c} for c in chunk], timeout=12)
            if r.status_code == 429:
                break
            if r.status_code != 200:
                continue
            arr = r.json()
            for c, item in zip(chunk, arr):
                data = item.get("data") or []
                tk = next((d.get("ticker") for d in data if d.get("exchCode") == "US" and d.get("ticker")), None)
                out[c] = tk or (data[0].get("ticker") if data else None)
        except Exception:
            continue
    return out


def get_13f(cik: str, openfigi_key: str = "") -> dict:
    cik = str(int(cik))
    filings = get_recent_13f(cik)
    if not filings:
        raise ValueError("이 기관의 13F-HR 신고를 찾을 수 없습니다.")
    latest, prev = filings[0], (filings[1] if len(filings) > 1 else None)
    cur = _aggregate(fetch_infotable(cik, latest["accession"]))
    prev_agg = _aggregate(fetch_infotable(cik, prev["accession"])) if prev else {}
    total = sum(v["value"] for v in cur.values())

    holdings = []
    for key, r in cur.items():
        prev_shares = prev_agg.get(key, {}).get("shares")
        delta = ((r["shares"] - prev_shares) / prev_shares * 100) if (prev_shares and prev_shares > 0) else None
        holdings.append({
            "issuer": r["issuer"], "cusip": r["cusip"], "ticker": None,
            "titleOfClass": r["titleOfClass"], "putCall": r["putCall"],
            "value": r["value"], "shares": r["shares"],
            "pct": (r["value"] / total * 100) if total else 0,
            "change": _classify(r["shares"], prev_shares),
            "deltaSharesPct": delta,
        })
    holdings.sort(key=lambda h: -h["value"])
    for i, h in enumerate(holdings):
        h["rank"] = i + 1

    tmap = resolve_tickers([h["cusip"] for h in holdings], openfigi_key)
    for h in holdings:
        h["ticker"] = tmap.get(h["cusip"].upper())

    exited = sorted(
        [{"issuer": r["issuer"], "cusip": r["cusip"], "prevValue": r["value"]}
         for k, r in prev_agg.items() if r["value"] > 0 and k not in cur],
        key=lambda x: -x["prevValue"])[:12]

    manager = next((m for m in MANAGERS if str(int(m["cik"])) == cik), None)
    return {
        "cik": cik, "manager": manager["label"] if manager else f"CIK {cik}",
        "reportDate": latest["reportDate"], "prevReportDate": prev["reportDate"] if prev else None,
        "filedAt": latest["filedAt"], "totalValue": total, "positions": len(holdings),
        "holdings": holdings, "exited": exited,
    }
