"""가짜 API 응답으로 수집·필터·지역분류 로직을 확인하는 테스트.

    python -m unittest discover tests
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch  # noqa: E402
from regions import RegionIndex  # noqa: E402

TO_TM = Transformer.from_crs("EPSG:4326", "EPSG:5174", always_xy=True)


def rec(name, addr, lng, lat, status="영업/정상", phone="02-123-4567", mng="M1"):
    x, y = TO_TM.transform(lng, lat) if lng else ("", "")
    return {"MNG_NO": mng, "BPLC_NM": name, "SALS_STTS_NM": status, "ROAD_NM_ADDR": addr,
            "LOTNO_ADDR": "", "TELNO": phone, "CRD_INFO_X": str(x), "CRD_INFO_Y": str(y),
            "LCPMT_YMD": "20200102", "CLSBIZ_YMD": ""}


RECORDS = [
    rec("강서 보청기센터", "서울특별시 강서구 공항대로", 126.8495, 37.5509, mng="A"),
    rec("오티콘 인천남동", "인천광역시 남동구 인하로", 126.7314, 37.4473, mng="B"),
    rec("Phonak 수원", "경기도 수원시 장안구 정조로", 127.0106, 37.3008, mng="C"),
    rec("폐업한 보청기", "서울특별시 은평구 통일로", 126.9290, 37.6027, status="폐업", mng="D"),
    rec("일반 의료기기상사", "서울특별시 중구 세종대로", 126.9780, 37.5665, mng="E"),
    rec("좌표없는 히어링", "부산광역시 해운대구 센텀로", None, None, mng="F"),
]


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = fetch.load_settings()
        cls.regions = RegionIndex()
        cls.items, cls.crs, _ = fetch.build(RECORDS, cls.settings, cls.regions, log=lambda *_: None)
        cls.by_id = {i["id"]: i for i in cls.items}

    def test_keyword_and_status_filter(self):
        self.assertEqual(sorted(self.by_id), ["A", "B", "C", "F"])

    def test_crs_autodetect(self):
        self.assertEqual(self.crs, "EPSG:5174")

    def test_regions_from_coords(self):
        self.assertEqual((self.by_id["A"]["sido"], self.by_id["A"]["sigungu"]), ("서울", "강서구"))
        self.assertEqual((self.by_id["B"]["sido"], self.by_id["B"]["sigungu"]), ("인천", "남동구"))
        self.assertEqual((self.by_id["C"]["sido"], self.by_id["C"]["sigungu"]), ("경기", "수원시 장안구"))
        self.assertAlmostEqual(self.by_id["A"]["lat"], 37.5509, places=3)

    def test_region_from_address_without_coords(self):
        f = self.by_id["F"]
        self.assertEqual((f["sido"], f["sigungu"], f["lat"]), ("부산", "해운대구", None))

    def test_matched_keywords(self):
        self.assertIn("phonak", self.by_id["C"]["keywords"])
        self.assertEqual(self.by_id["A"]["permit_date"], "2020-01-02")


class ApiTest(unittest.TestCase):
    def test_pagination_and_key_decoding(self):
        pages = {1: RECORDS[:4], 2: RECORDS[4:]}
        seen_keys = []

        def fake_get(url, params, timeout):
            seen_keys.append(params["serviceKey"])
            body = {"response": {"header": {"resultCode": "00"},
                                 "body": {"totalCount": len(RECORDS),
                                          "items": {"item": pages.get(params["pageNo"], [])}}}}
            return mock.Mock(status_code=200, text=json.dumps(body, ensure_ascii=False))

        settings = fetch.load_settings()
        settings["api"]["endpoint"] = "https://example.invalid/api"
        settings["api"]["page_size"] = 4
        with mock.patch.dict(os.environ, {"DATA_GO_KR_KEY": "abc%2Bdef%3D%3D"}), \
                mock.patch.object(fetch.requests, "get", side_effect=fake_get):
            records, total = fetch.fetch_all(settings)
        self.assertEqual((len(records), total), (6, 6))
        self.assertEqual(seen_keys[0], "abc+def==")

    def test_xml_error_message(self):
        xml = ("<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR"
               "</returnAuthMsg><returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>")
        settings = fetch.load_settings()
        settings["api"]["endpoint"] = "https://example.invalid/api"
        with mock.patch.dict(os.environ, {"DATA_GO_KR_KEY": "k"}), \
                mock.patch.object(fetch.requests, "get", return_value=mock.Mock(status_code=200, text=xml)):
            with self.assertRaisesRegex(fetch.ApiError, "인증키"):
                fetch.call_api(settings, 1, 10)


if __name__ == "__main__":
    unittest.main()
