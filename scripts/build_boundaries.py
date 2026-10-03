"""행정동 경계(vuski/admdongkor)를 시/도·시/군/구 경계로 합쳐 docs/data에 저장.

행정구역이 바뀌었을 때만 다시 실행하면 된다:
    python scripts/build_boundaries.py ver20260701
"""
import json
import sys
import urllib.request
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from regions import ROOT, SIDO_SHORT, pretty_sigungu  # noqa: E402

VERSION = sys.argv[1] if len(sys.argv) > 1 else "ver20260701"
URL = f"https://raw.githubusercontent.com/vuski/admdongkor/master/{VERSION}/HangJeongDong_{VERSION}.geojson"


def rounded(geom, digits=5):
    def r(c):
        if isinstance(c[0], (list, tuple)):
            return [r(x) for x in c]
        return [round(c[0], digits), round(c[1], digits)]
    g = mapping(geom)
    return {"type": g["type"], "coordinates": r(g["coordinates"])}


def main():
    print(f"다운로드: {URL}")
    with urllib.request.urlopen(URL) as resp:
        src = json.load(resp)

    sgg_parts, sido_parts = {}, {}
    for f in src["features"]:
        p = f["properties"]
        sido = SIDO_SHORT[p["sidonm"]]
        sgg = pretty_sigungu(p["sggnm"])
        geom = shape(f["geometry"]).buffer(0)
        sgg_parts.setdefault((sido, sgg, p["sgg"]), []).append(geom)
        sido_parts.setdefault(sido, []).append(geom)

    sgg_features = []
    for (sido, sgg, code), parts in sorted(sgg_parts.items(), key=lambda x: x[0][2]):
        geom = unary_union(parts).simplify(0.0004, preserve_topology=True)
        sgg_features.append({"type": "Feature",
                             "properties": {"code": code, "sido": sido, "sigungu": sgg},
                             "geometry": rounded(geom)})

    sido_features = []
    for sido, parts in sido_parts.items():
        geom = unary_union(parts).simplify(0.002, preserve_topology=True)
        sido_features.append({"type": "Feature", "properties": {"sido": sido},
                              "geometry": rounded(geom, 4)})

    out = ROOT / "docs" / "data"
    out.mkdir(parents=True, exist_ok=True)
    for name, feats in (("sigungu", sgg_features), ("sido", sido_features)):
        path = out / f"{name}.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "source": VERSION, "features": feats},
                                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{path.relative_to(ROOT)}: {len(feats)}개, {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
