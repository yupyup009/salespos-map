# 보청기 판매업체 지도

공공데이터포털 **「행정안전부_건강_의료기기판매(임대)업 조회서비스」** Open API에서 의료기기판매(임대)업 업체를 받아 옵니다. 그중 보청기 관련 업체만 골라 지도와 엑셀형 표로 보여 주며, 데이터는 매일 자동으로 갱신됩니다.

- **1페이지 (지도)**: 전국 업체를 점으로 표시합니다. 시/도나 시/군/구를 누르면 그 구역 경계가 표시되고, 그 지역 업체만 나타납니다.
- **2페이지 (리스트)**: 전체 업체를 표로 보여 줍니다. 정렬, 검색, 지역 필터를 쓸 수 있고 엑셀·CSV로 내려받을 수 있습니다. 행을 누르면 지도에서 그 업체 위치로 이동합니다.

## 처음 설정 (한 번만)

### 1. End Point 넣기
1. [공공데이터포털](https://www.data.go.kr) → 마이페이지 → **데이터활용 → Open API → 활용신청 현황**으로 갑니다. 목록에서 「행정안전부_건강_의료기기판매(임대)업 조회서비스」를 누릅니다.
2. 상세 화면의 **End Point** 주소(`https://apis.data.go.kr/...` 형태)를 복사합니다. 상세기능(오퍼레이션)이 여러 개면 *목록 조회*에 해당하는 요청 주소를 씁니다.
3. 이 저장소의 [`config/settings.json`](config/settings.json)을 GitHub에서 엽니다. 연필(✏️) 버튼을 눌러 아래 부분을 바꾸고 커밋합니다.
   ```json
   "endpoint": "여기에_End_Point_붙여넣기",
   ```
   예: `"endpoint": "https://apis.data.go.kr/1741000/.../info",`

### 2. 인증키 등록 (저장소에 직접 쓰지 마세요)
GitHub 저장소 → **Settings → Secrets and variables → Actions → New repository secret**에서 등록합니다.

| 이름 | 값 | 필수 |
|---|---|---|
| `DATA_GO_KR_KEY` | 공공데이터포털 **일반 인증키** (Encoding/Decoding 아무거나) | ✅ |
| `KAKAO_REST_KEY` | 카카오 REST API 키 (가려진 상세주소·전화번호 자동 보완) | 선택 |

### 3. API 구조 확인 (0단계)
**Actions** 탭 → **API 구조 확인 (0단계)** → **Run workflow**를 누릅니다. 로그에 응답 필드, 자동 매핑 결과, 좌표 예시가 출력됩니다.
- 매핑이 `(못 찾음)`인 항목이 있으면 [`config/settings.json`](config/settings.json)의 `fields`에 실제 필드명을 추가하면 됩니다.
- 인증키는 활용신청 승인 후 **1~2시간 뒤에야 동작**하는 경우가 많습니다. `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`가 나오면 잠시 뒤 다시 시도하세요.

### 4. 첫 수집
**Actions → 업체 데이터 업데이트 → Run workflow**를 누르면 `docs/data/companies.json`이 만들어집니다. 그다음부터는 **매일 한국시간 새벽 3시 47분**에 자동으로 실행됩니다.

> 예약 실행(schedule)은 저장소의 **기본 브랜치(main)** 에서만 동작합니다. 작업 브랜치를 main에 합친 뒤부터 매일 자동 갱신됩니다.

### 5. 홈페이지 공개 (GitHub Pages)
**Settings → Pages → Build and deployment**에서 Source를 *Deploy from a branch*, Branch를 `main` / `/docs`로 정하고 저장합니다. 1~2분 뒤 `https://<아이디>.github.io/salespos-map/` 에서 볼 수 있습니다.

## 업체 선별 기준 바꾸기
- [`config/keywords.txt`](config/keywords.txt): 사업장명에 이 단어가 들어가면 포함합니다 (보청기, 난청, 히어링, 오티콘, 포낙 … 영문 포함).
- [`config/exclude.txt`](config/exclude.txt): 키워드에 걸렸지만 관계없는 업체를 빼는 목록입니다.
- 폐업·휴업·취소 업체는 자동으로 제외됩니다.

## 동작 방식
```
공공데이터 API ─▶ scripts/fetch.py ─▶ docs/data/companies.json ─▶ docs/index.html (지도)
   (전체 페이지)    키워드 필터                                    └▶ docs/list.html  (리스트)
                    영업중 필터
                    좌표 변환(TM→위경도, 좌표계 자동 판별)
                    지역 분류(좌표가 속한 시/군/구 경계)
                    [선택] 카카오로 가려진 주소·전화 보완
```
- **좌표**: 행안부 인허가 데이터의 TM 좌표(EPSG:5174 등)를 위경도로 바꿉니다. 좌표계는 주소와 대조해 자동으로 판별합니다. 지도 표시에는 외부 API 키가 필요 없습니다.
- **지역 분류**: 좌표가 어느 시/군/구 경계 안에 있는지로 정합니다. 좌표가 없으면 주소에서 읽습니다. 경계 데이터는 2026-07 기준 행정구역입니다(인천 제물포구·영종구·검단구, 전남광주통합특별시 반영). 행정구역이 다시 바뀌면 `python scripts/build_boundaries.py <버전>`으로 경계를 새로 만듭니다.
- **자동보완 표시**: 카카오로 채운 주소와 전화번호에는 `자동보완` 표시가 붙습니다. 좌표로 찾은 주소는 가장 가까운 건물 주소라서 실제 업체 주소와 다를 수 있습니다.
- **안전장치**: API 장애로 업체 수가 절반 아래로 줄면 기존 데이터를 덮어쓰지 않습니다. 신규·제외 업체 이력은 `docs/data/changes.json`에 남고, 화면 상단 "최근 변경"에서 볼 수 있습니다.

## 내 컴퓨터에서 실행
```bash
pip install -r requirements.txt
export DATA_GO_KR_KEY="인증키"
python scripts/fetch.py --inspect   # API 구조 확인
python scripts/fetch.py             # 수집
python -m http.server -d docs 8000  # http://localhost:8000 에서 확인
python -m unittest discover tests   # 테스트
```

## 데이터 출처
- 업체: 공공데이터포털, 행정안전부_건강_의료기기판매(임대)업 조회서비스
- 행정구역 경계: [vuski/admdongkor](https://github.com/vuski/admdongkor) (통계청 행정동 경계 기반)
- 지도: © OpenStreetMap contributors
