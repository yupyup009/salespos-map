"""행정구역 이름 정규화와 좌표→행정구역 판별."""
import json
import re
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
SIGUNGU_GEOJSON = ROOT / "docs" / "data" / "sigungu.geojson"

# 경계 데이터의 시/도 정식 명칭 → 화면 표시용 짧은 이름
SIDO_SHORT = {
    "서울특별시": "서울",
    "부산광역시": "부산",
    "대구광역시": "대구",
    "인천광역시": "인천",
    "대전광역시": "대전",
    "울산광역시": "울산",
    "세종특별자치시": "세종",
    "경기도": "경기",
    "강원특별자치도": "강원",
    "충청북도": "충북",
    "충청남도": "충남",
    "전북특별자치도": "전북",
    "전남광주통합특별시": "광주·전남",
    "경상북도": "경북",
    "경상남도": "경남",
    "제주특별자치도": "제주",
}

# 주소에 나올 수 있는 옛 명칭·약칭 → 짧은 이름
SIDO_ALIASES = {
    **{k: v for k, v in SIDO_SHORT.items()},
    **{v: v for v in SIDO_SHORT.values()},
    "강원도": "강원",
    "전라북도": "전북",
    "광주광역시": "광주·전남",
    "전라남도": "광주·전남",
    "광주": "광주·전남",
    "전남": "광주·전남",
    "제주도": "제주",
    "세종시": "세종",
    "서울시": "서울",
}

SIDO_ORDER = ["서울", "인천", "경기", "부산", "대구", "대전", "울산", "세종",
              "강원", "충북", "충남", "전북", "광주·전남", "경북", "경남", "제주"]


def pretty_sigungu(name: str) -> str:
    """'수원시장안구' → '수원시 장안구'"""
    m = re.match(r"^(.+?시)(.+구)$", name or "")
    return f"{m.group(1)} {m.group(2)}" if m else (name or "")


class RegionIndex:
    def __init__(self, path: Path = SIGUNGU_GEOJSON):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.features = data["features"]
        self.geoms = [shape(f["geometry"]) for f in self.features]
        self.tree = STRtree(self.geoms)
        # 시/도별 시군구 이름 목록 (주소 파싱용)
        self.by_sido = {}
        for f in self.features:
            p = f["properties"]
            self.by_sido.setdefault(p["sido"], set()).add(p["sigungu"])

    def locate(self, lng: float, lat: float):
        """좌표가 속한 (시/도, 시/군/구). 바다 등 경계 밖이면 가장 가까운 구역."""
        pt = Point(lng, lat)
        for i in self.tree.query(pt, predicate="intersects"):
            p = self.features[i]["properties"]
            return p["sido"], p["sigungu"]
        i = self.tree.nearest(pt)
        if i is not None and self.geoms[i].distance(pt) < 0.05:  # 약 5km 이내 섬·해안
            p = self.features[i]["properties"]
            return p["sido"], p["sigungu"]
        return None, None

    def parse_address(self, address: str):
        """주소 문자열에서 (시/도, 시/군/구) 추출. 못 찾으면 None."""
        if not address:
            return None, None
        tokens = address.replace(",", " ").split()
        if not tokens:
            return None, None
        sido = SIDO_ALIASES.get(tokens[0])
        if not sido:
            return None, None
        known = self.by_sido.get(sido, set())
        rest = tokens[1:4]
        candidates = []
        if len(rest) >= 2:
            candidates.append(pretty_sigungu(rest[0] + rest[1]))
        if rest:
            candidates.append(rest[0])
        for c in candidates:
            if c in known:
                return sido, c
        # 세종시는 시군구가 없음
        if sido == "세종":
            return sido, "세종시"
        # 경계 데이터에 없는 옛 구 이름이라도 텍스트로는 남긴다
        sg = rest[0] if rest and re.search(r"(시|군|구)$", rest[0]) else None
        if sg and len(rest) >= 2 and sg.endswith("시") and rest[1].endswith("구"):
            sg = f"{sg} {rest[1]}"
        return sido, sg
