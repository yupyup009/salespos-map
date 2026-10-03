"""공공데이터포털 의료기기판매(임대)업 API → 보청기 업체 목록(docs/data/companies.json).

사용법
    python scripts/fetch.py --inspect   # API 1페이지만 받아 필드 구조를 확인 (0단계)
    python scripts/fetch.py             # 전체 수집 후 docs/data/*.json 갱신

환경변수
    DATA_GO_KR_KEY       공공데이터포털 인증키 (필수, Encoding/Decoding 둘 다 가능)
    DATA_GO_KR_ENDPOINT  End Point (선택, 없으면 config/settings.json 값 사용)
    KAKAO_REST_KEY       카카오 REST 키 (선택, 있으면 가려진 주소·전화번호 자동 보완)
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

import requests
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from regions import ROOT, SIDO_ORDER, RegionIndex  # noqa: E402

CONFIG = ROOT / "config"
OUT = ROOT / "docs" / "data"
CACHE = ROOT / "data" / "cache" / "kakao.json"
KST = timezone(timedelta(hours=9))

# 좌표 자동 판별 후보 (행안부 인허가 데이터는 보통 EPSG:5174)
CRS_CANDIDATES = ["EPSG:5174", "EPSG:5186", "EPSG:5181", "EPSG:5179", "EPSG:2097"]


# End Point 뒤에 붙는 상세기능(오퍼레이션) 이름 후보. 서비스 주소만 넣었을 때 차례로 시도한다.
OPERATION_CANDIDATES = ["info", "getInfo", "list", "getList", "search", "searchList",
                        "getMedicalDeviceSalesRentalList", "getMedicalDeviceSalesRentalInfo",
                        "medical_device_sales_rental_info", "selectList"]


class ApiError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- 설정 읽기

def load_settings():
    return json.loads((CONFIG / "settings.json").read_text(encoding="utf-8"))


def load_lines(name):
    path = CONFIG / name
    if not path.exists():
        return []
    lines = (l.strip() for l in path.read_text(encoding="utf-8").splitlines())
    return [l for l in lines if l and not l.startswith("#")]


def norm(text):
    return re.sub(r"\s+", "", str(text or "")).lower()


# ---------------------------------------------------------------- API 호출

def service_key():
    key = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if not key:
        raise ApiError("DATA_GO_KR_KEY 환경변수(인증키)가 없습니다. README의 '인증키 등록'을 확인하세요.")
    # Encoding 키(% 포함)는 풀어서 넘긴다. requests가 다시 한 번만 인코딩한다.
    return unquote(key) if "%" in key else key


def endpoint(settings):
    url = os.environ.get("DATA_GO_KR_ENDPOINT", "").strip() or settings["api"]["endpoint"].strip()
    if not url.startswith("http"):
        raise ApiError("End Point가 비어 있습니다. config/settings.json의 api.endpoint에 붙여넣으세요.")
    return url


def find_records(obj):
    """응답 JSON 어딘가에 있는 업체 목록(dict 리스트)을 찾는다."""
    if isinstance(obj, dict):
        for key in ("item", "items", "row", "data", "list"):
            v = obj.get(key)
            if isinstance(v, dict) and looks_like_record(v):
                return [v]
            if isinstance(v, list) and (not v or looks_like_record(v[0])):
                return v
        for v in obj.values():
            if isinstance(v, (dict, list)):
                found = find_records(v)
                if found is not None:
                    return found
    elif isinstance(obj, list):
        if obj and looks_like_record(obj[0]):
            return obj
        for v in obj:
            found = find_records(v)
            if found is not None:
                return found
    return None


def looks_like_record(d):
    return isinstance(d, dict) and sum(1 for v in d.values() if not isinstance(v, (dict, list))) >= 4


def find_value(obj, names):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in names and not isinstance(v, (dict, list)):
                return v
        for v in obj.values():
            r = find_value(v, names)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_value(v, names)
            if r is not None:
                return r
    return None


def xml_to_obj(text):
    root = ET.fromstring(text)

    def conv(el):
        children = list(el)
        if not children:
            return (el.text or "").strip()
        out = {}
        for c in children:
            v = conv(c)
            if c.tag in out:
                if not isinstance(out[c.tag], list):
                    out[c.tag] = [out[c.tag]]
                out[c.tag].append(v)
            else:
                out[c.tag] = v
        return out

    return {root.tag: conv(root)}


def check_error(obj):
    code = find_value(obj, {"resultCode", "returnReasonCode", "RESULT_CODE"})
    msg = find_value(obj, {"resultMsg", "returnAuthMsg", "errMsg", "RESULT_MSG"})
    ok_codes = {None, "", "00", "0", "000", "INFO-000", "NORMAL_SERVICE", "0000"}
    if str(code) not in ok_codes and code is not None:
        hint = ""
        if "SERVICE_KEY" in str(msg) or str(code) in {"30", "31"}:
            hint = (" → 인증키 문제입니다. 활용신청 승인 후 1~2시간 뒤에 동작하는 경우가 많고,"
                    " Encoding/Decoding 키를 바꿔 넣어 보세요.")
        elif str(code) == "12":
            hint = (" → End Point 주소가 틀렸습니다. 활용신청 상세 화면의 '상세기능' 표에서"
                    " 요청주소(서비스 주소 뒤에 /기능이름 이 붙은 것)를 넣어 주세요.")
        raise ApiError(f"API 오류 (코드 {code}): {msg}{hint}", code=str(code))


def call_api(settings, page, size, retries=4, url=None):
    api = settings["api"]
    params = dict(api.get("params", {}))
    params.update({"serviceKey": service_key(), api["page_param"]: page, api["size_param"]: size})
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url or resolve_endpoint(settings), params=params, timeout=60)
            text = r.text.strip()
            if r.status_code >= 500:
                raise ApiError(f"HTTP {r.status_code}")
            if r.status_code >= 400:
                try:
                    check_error(json.loads(text) if text[:1] in "{[" else xml_to_obj(text))
                except (ET.ParseError, json.JSONDecodeError):
                    pass
                raise ApiError(f"HTTP {r.status_code}: {text[:300]}")
            obj = json.loads(text) if text[:1] in "{[" else xml_to_obj(text)
            if find_records(obj) is None:
                check_error(obj)
            return obj
        except (requests.RequestException, ApiError, ET.ParseError, json.JSONDecodeError) as e:
            last = e
            if isinstance(e, ApiError) and not str(e).startswith("HTTP 5"):
                raise
            time.sleep(2 ** (attempt + 1))
    raise ApiError(f"API 호출 실패 (페이지 {page}): {last}")


_resolved = {}


def resolve_endpoint(settings):
    """설정된 주소가 '서비스 없음(12)'이면 상세기능 이름을 붙여 가며 맞는 주소를 찾는다."""
    base = endpoint(settings)
    if base in _resolved:
        return _resolved[base]
    _resolved[base] = base
    try:
        call_api(settings, 1, 1, url=base)
        return base
    except ApiError as e:
        if e.code != "12":
            raise
        first_error = e
    for op in OPERATION_CANDIDATES:
        url = f"{base.rstrip('/')}/{op}"
        try:
            call_api(settings, 1, 1, url=url)
        except ApiError as e:
            if e.code == "12" or str(e).startswith("HTTP 404"):
                continue
            raise
        print(f"상세기능 주소를 자동으로 찾았습니다: {url}")
        print("  (config/settings.json의 endpoint를 이 주소로 바꿔 두면 다음부터 바로 사용합니다)")
        _resolved[base] = url
        return url
    raise first_error


def fetch_all(settings):
    size = int(settings["api"].get("page_size", 1000))
    records, page, total = [], 1, None
    while True:
        obj = call_api(settings, page, size)
        batch = find_records(obj) or []
        if total is None:
            t = find_value(obj, {"totalCount", "total_count", "TOTAL_COUNT", "list_total_count"})
            total = int(t) if t not in (None, "") else None
            print(f"전체 건수: {total if total is not None else '알 수 없음'}")
        records.extend(batch)
        print(f"  {page}페이지: {len(batch)}건 (누적 {len(records)})")
        # 서버가 numOfRows를 더 작게 잘라 줄 수도 있으므로 totalCount를 기준으로 끝을 판단한다
        if not batch or (total is not None and len(records) >= total) or (total is None and len(batch) < size):
            break
        page += 1
        time.sleep(0.2)
    return records, total


# ---------------------------------------------------------------- 필드 매핑

class Mapper:
    def __init__(self, fields, sample):
        self.cols = {}
        keys = {}
        for rec in sample:
            for k in rec:
                keys.setdefault(k.lower(), k)
        for logical, cands in fields.items():
            for c in cands:
                if c.lower() in keys:
                    self.cols[logical] = keys[c.lower()]
                    break

    def get(self, rec, logical):
        col = self.cols.get(logical)
        v = rec.get(col) if col else None
        return str(v).strip() if v not in (None, "") else ""


# ---------------------------------------------------------------- 좌표

def to_float(v):
    try:
        f = float(str(v).replace(",", ""))
        return f if f != 0 else None
    except (TypeError, ValueError):
        return None


def in_korea(lng, lat):
    return 124.0 < lng < 132.5 and 33.0 < lat < 39.0


class CoordConverter:
    def __init__(self, crs):
        self.crs = crs
        self.tf = None if crs == "WGS84" else Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    def __call__(self, x, y):
        if x is None or y is None:
            return None
        if self.crs == "WGS84":
            lng, lat = (x, y) if in_korea(x, y) else (y, x)
        else:
            lng, lat = self.tf.transform(x, y)
        return (round(lng, 6), round(lat, 6)) if in_korea(lng, lat) else None


def choose_crs(setting, rows, regions):
    """좌표계를 자동 판별: 변환한 점의 시/도가 주소의 시/도와 가장 많이 맞는 좌표계."""
    if setting and setting != "auto":
        return setting
    pts = [(to_float(r["x"]), to_float(r["y"]), r["addr"]) for r in rows]
    pts = [p for p in pts if p[0] is not None and p[1] is not None][:300]
    if not pts:
        return "EPSG:5174"
    if sum(1 for x, y, _ in pts if in_korea(x, y) or in_korea(y, x)) > len(pts) * 0.8:
        return "WGS84"
    best, best_score = "EPSG:5174", -1
    for crs in CRS_CANDIDATES:
        conv = CoordConverter(crs)
        score = 0
        for x, y, addr in pts:
            ll = conv(x, y)
            if not ll:
                continue
            sido, _ = regions.locate(*ll)
            addr_sido, _ = regions.parse_address(addr)
            score += 2 if (sido and sido == addr_sido) else (1 if sido else 0)
        if score > best_score:
            best, best_score = crs, score
    return best


# ---------------------------------------------------------------- 카카오 보완 (선택)

def is_masked_addr(addr):
    return not addr or "*" in addr or not re.search(r"\d", addr)


def is_masked_phone(phone):
    return not phone or "*" in phone or len(re.sub(r"\D", "", phone)) < 7


class Kakao:
    def __init__(self, key):
        self.key = key
        self.cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
        self.calls = 0

    def _get(self, path, params):
        cache_key = path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        if cache_key in self.cache:
            return self.cache[cache_key]
        r = requests.get(f"https://dapi.kakao.com{path}", params=params,
                         headers={"Authorization": f"KakaoAK {self.key}"}, timeout=20)
        self.calls += 1
        if r.status_code != 200:
            print(f"  카카오 API 오류 {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        self.cache[cache_key] = data
        time.sleep(0.05)
        return data

    def address(self, lng, lat):
        d = self._get("/v2/local/geo/coord2address.json", {"x": lng, "y": lat})
        docs = (d or {}).get("documents") or []
        if not docs:
            return ""
        road = (docs[0].get("road_address") or {}).get("address_name")
        jibun = (docs[0].get("address") or {}).get("address_name")
        return road or jibun or ""

    def phone(self, name, lng, lat):
        d = self._get("/v2/local/search/keyword.json",
                      {"query": name, "x": lng, "y": lat, "radius": 300, "sort": "distance"})
        for doc in (d or {}).get("documents") or []:
            a, b = norm(doc.get("place_name")), norm(name)
            if doc.get("phone") and (a in b or b in a):
                return doc["phone"]
        return ""

    def save(self):
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- 처리

def is_closed(status, detail, close_date, words):
    text = f"{status} {detail}"
    return bool(close_date) or any(w in text for w in words)


def build(records, settings, regions, kakao=None, log=print):
    keywords = load_lines("keywords.txt")
    excludes = [norm(x) for x in load_lines("exclude.txt")]
    kw_norm = [(k, norm(k)) for k in keywords]
    mapper = Mapper(settings["fields"], records[:200])
    if "name" not in mapper.cols:
        raise ApiError("응답에서 사업장명 필드를 찾지 못했습니다. --inspect 결과를 보고 "
                       "config/settings.json의 fields.name에 실제 필드명을 추가하세요.")

    rows = []
    for rec in records:
        g = lambda k: mapper.get(rec, k)  # noqa: E731
        name = g("name")
        n = norm(name)
        hits = [k for k, kn in kw_norm if kn and kn in n]
        if not hits or any(e and e in n for e in excludes):
            continue
        if g("update_type").upper() == "D":  # 삭제된 인허가 정보
            continue
        if is_closed(g("status"), g("detail_status"), g("close_date"), settings["closed_status_words"]):
            continue
        rows.append({"rec": rec, "name": name, "hits": hits, "addr": g("road_addr") or g("jibun_addr"),
                     "x": g("x"), "y": g("y"), "g": {k: g(k) for k in settings["fields"]}})

    crs = choose_crs(settings.get("coord_crs", "auto"), rows, regions)
    conv = CoordConverter(crs)
    log(f"좌표계: {crs}")

    items, seen = [], set()
    for r in rows:
        f = r["g"]
        ll = conv(to_float(r["x"]), to_float(r["y"]))
        addr, addr_auto = r["addr"], False
        phone, phone_auto = f["phone"], False
        if kakao and ll:
            if is_masked_addr(addr):
                found = kakao.address(*ll)
                if found:
                    addr, addr_auto = found, True
            if is_masked_phone(phone):
                found = kakao.phone(r["name"], *ll)
                if found:
                    phone, phone_auto = found, True

        sido, sigungu = regions.locate(*ll) if ll else (None, None)
        if not sido:
            sido, sigungu = regions.parse_address(addr or r["addr"])

        dedupe = (norm(r["name"]), norm(addr))
        if dedupe in seen:
            continue
        seen.add(dedupe)
        uid = f["id"] or hashlib.sha1(f"{r['name']}|{r['addr']}|{r['x']}|{r['y']}".encode()).hexdigest()[:12]
        items.append({
            "id": uid,
            "name": r["name"],
            "sido": sido or "미분류",
            "sigungu": sigungu or "미분류",
            "address": addr,
            "address_auto": addr_auto,
            "phone": phone,
            "phone_auto": phone_auto,
            "keywords": r["hits"],
            "permit_date": fmt_date(f["permit_date"]),
            "status": f["detail_status"] or f["status"],
            "lat": ll[1] if ll else None,
            "lng": ll[0] if ll else None,
        })

    order = {s: i for i, s in enumerate(SIDO_ORDER)}
    items.sort(key=lambda i: (order.get(i["sido"], 99), i["sigungu"], i["name"]))
    return items, crs, mapper


def fmt_date(v):
    d = re.sub(r"\D", "", v or "")[:8]
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else (v or "")


def write_outputs(items, total, crs):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "companies.json"
    prev = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    prev_items = {i["id"]: i for i in prev.get("items", [])}

    # API 장애로 데이터가 크게 줄면 덮어쓰지 않는다
    if prev_items and len(items) < len(prev_items) * 0.5:
        raise ApiError(f"업체 수가 {len(prev_items)} → {len(items)}로 급감했습니다. "
                       "API 일시 장애로 보고 이번 갱신을 건너뜁니다.")

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    cur = {i["id"]: i for i in items}
    added = [cur[k] for k in cur if k not in prev_items]
    removed = [prev_items[k] for k in prev_items if k not in cur]

    if items == prev.get("items"):
        print("변경 없음")
        return False

    path.write_text(json.dumps({
        "updated_at": now,
        "source_total": total,
        "count": len(items),
        "located": sum(1 for i in items if i["lat"] is not None),
        "crs": crs,
        "items": items,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    chg_path = OUT / "changes.json"
    changes = json.loads(chg_path.read_text(encoding="utf-8")) if chg_path.exists() else []
    if prev_items and (added or removed):
        brief = lambda i: {"id": i["id"], "name": i["name"], "sido": i["sido"], "sigungu": i["sigungu"]}  # noqa: E731
        changes.insert(0, {"date": now, "added": [brief(i) for i in added],
                           "removed": [brief(i) for i in removed]})
        chg_path.write_text(json.dumps(changes[:60], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {len(items)}개 업체 (신규 {len(added) if prev_items else '-'}, 제외 {len(removed)})")
    return True


# ---------------------------------------------------------------- 0단계 점검

def inspect(settings):
    obj = call_api(settings, 1, 10)
    recs = find_records(obj) or []
    total = find_value(obj, {"totalCount", "total_count", "TOTAL_COUNT", "list_total_count"})
    print(f"\n전체 건수(totalCount): {total}\n받은 샘플: {len(recs)}건\n")
    if not recs:
        print("업체 목록을 찾지 못했습니다. 원본 응답 앞부분:")
        print(json.dumps(obj, ensure_ascii=False)[:2000])
        return
    print("■ 응답 필드와 첫 번째 값")
    for k, v in recs[0].items():
        print(f"  {k:<28} {str(v)[:60]}")
    mapper = Mapper(settings["fields"], recs)
    print("\n■ 자동 매핑 결과 (비어 있으면 config/settings.json fields에 필드명 추가)")
    for logical in settings["fields"]:
        print(f"  {logical:<14} ← {mapper.cols.get(logical, '(못 찾음)')}")
    xs = [to_float(mapper.get(r, "x")) for r in recs]
    ys = [to_float(mapper.get(r, "y")) for r in recs]
    pairs = [(x, y) for x, y in zip(xs, ys) if x and y]
    if pairs:
        print(f"\n■ 좌표 예시: {pairs[:3]}")
        print("  (124~132 / 33~39 범위면 위경도, 수십만 단위면 TM 좌표 → 자동 변환)")
    print("\n■ 주소·전화 예시")
    for r in recs[:5]:
        print(f"  {mapper.get(r, 'name')} | {mapper.get(r, 'road_addr') or mapper.get(r, 'jibun_addr')}"
              f" | {mapper.get(r, 'phone')} | {mapper.get(r, 'status')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true", help="API 1페이지만 받아 필드 구조 출력")
    args = ap.parse_args()
    settings = load_settings()
    try:
        if args.inspect:
            inspect(settings)
            return
        records, total = fetch_all(settings)
        if not records:
            raise ApiError("API에서 받은 데이터가 0건입니다.")
        regions = RegionIndex()
        key = os.environ.get("KAKAO_REST_KEY", "").strip()
        kakao = Kakao(key) if key else None
        items, crs, _ = build(records, settings, regions, kakao)
        if kakao:
            kakao.save()
            print(f"카카오 API 호출 {kakao.calls}회 (나머지는 캐시)")
        write_outputs(items, total or len(records), crs)
    except ApiError as e:
        print(f"\n[오류] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
