// 1페이지: 지도
const KOREA_BOUNDS = [[33.0, 124.6], [38.7, 131.0]];
const SIDO_ORDER = ["서울", "인천", "경기", "부산", "대구", "대전", "울산", "세종",
  "강원", "충북", "충남", "전북", "광주·전남", "경북", "경남", "제주", "미분류"];

const map = L.map("map", { preferCanvas: true, zoomControl: true }).fitBounds(KOREA_BOUNDS);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);

const cluster = L.markerClusterGroup({
  disableClusteringAtZoom: 12,
  showCoverageOnHover: false,
  maxClusterRadius: 45,
  chunkedLoading: true,
});
map.addLayer(cluster);

const highlight = L.layerGroup().addTo(map);
let sidoGeo = null;
let sigunguGeo = null;
let items = [];
const markers = new Map(); // id → marker
const state = { sido: null, sigungu: null, q: "" };

function popupHtml(i) {
  const auto = '<span class="tag">자동보완</span>';
  const tel = i.phone ? `<a href="tel:${esc(i.phone.replace(/[^\d+]/g, ""))}">${esc(i.phone)}</a>` : "-";
  return `<div class="popup">
    <h3>${esc(i.name)}</h3>
    <p>${esc(i.address || "-")}${i.address_auto ? auto : ""}</p>
    <p>☎ ${tel}${i.phone_auto ? auto : ""}</p>
    <p class="kw">${esc(i.sido)} ${esc(i.sigungu)} · 키워드: ${esc(i.keywords.join(", "))}${
      i.permit_date ? ` · 인허가 ${esc(i.permit_date)}` : ""}</p>
  </div>`;
}

function matches(i) {
  if (state.sido && i.sido !== state.sido) return false;
  if (state.sigungu && i.sigungu !== state.sigungu) return false;
  if (state.q && !i.name.toLowerCase().includes(state.q)) return false;
  return true;
}

function refreshMarkers() {
  cluster.clearLayers();
  const shown = items.filter((i) => i.lat != null && matches(i)).map((i) => markers.get(i.id));
  cluster.addLayers(shown);
}

async function drawHighlight() {
  highlight.clearLayers();
  if (!state.sido) {
    map.fitBounds(KOREA_BOUNDS);
    return;
  }
  let feats;
  if (state.sigungu) {
    sigunguGeo = sigunguGeo || await loadJSON("data/sigungu.geojson", { features: [] });
    feats = sigunguGeo.features.filter((f) => f.properties.sido === state.sido && f.properties.sigungu === state.sigungu);
  } else {
    feats = sidoGeo.features.filter((f) => f.properties.sido === state.sido);
  }
  if (feats.length) {
    const layer = L.geoJSON({ type: "FeatureCollection", features: feats }, {
      style: { color: "#1f6feb", weight: 2, fillColor: "#1f6feb", fillOpacity: 0.08 },
      interactive: false,
    }).addTo(highlight);
    map.fitBounds(layer.getBounds(), { padding: [20, 20] });
  } else {
    // 경계 데이터에 없는 이름(옛 구 이름 등)이면 해당 업체들 위치로 이동
    const pts = items.filter((i) => i.lat != null && matches(i)).map((i) => [i.lat, i.lng]);
    if (pts.length) map.fitBounds(pts, { padding: [40, 40], maxZoom: 14 });
  }
}

function renderRegions() {
  const tree = new Map();
  for (const i of items) {
    if (state.q && !i.name.toLowerCase().includes(state.q)) continue;
    if (!tree.has(i.sido)) tree.set(i.sido, new Map());
    const sg = tree.get(i.sido);
    sg.set(i.sigungu, (sg.get(i.sigungu) || 0) + 1);
  }
  const sidos = [...tree.keys()].sort((a, b) => SIDO_ORDER.indexOf(a) - SIDO_ORDER.indexOf(b));
  const box = document.getElementById("regions");
  box.innerHTML = sidos.map((s) => {
    const sg = tree.get(s);
    const total = [...sg.values()].reduce((a, b) => a + b, 0);
    const open = state.sido === s;
    const rows = [...sg.entries()].sort((a, b) => a[0].localeCompare(b[0], "ko")).map(([name, n]) =>
      `<div class="region sgg ${open && state.sigungu === name ? "on" : ""}" data-sido="${esc(s)}" data-sgg="${esc(name)}">
        <span>${esc(name)}</span><span class="n">${n}</span></div>`).join("");
    return `<div class="region sido ${open ? "open" : ""} ${open && !state.sigungu ? "on" : ""}" data-sido="${esc(s)}">
        <span>${esc(s)}</span><span class="n">${total}</span></div>
      <div class="sgg-wrap ${open ? "open" : ""}">${rows}</div>`;
  }).join("") || '<div class="region"><span class="n">검색 결과 없음</span></div>';
}

function select(sido, sigungu) {
  state.sido = sido;
  state.sigungu = sigungu;
  renderRegions();
  refreshMarkers();
  drawHighlight();
}

document.getElementById("regions").addEventListener("click", (e) => {
  const el = e.target.closest(".region[data-sido]");
  if (!el) return;
  const { sido, sgg } = el.dataset;
  if (sgg) select(sido, sgg);
  else if (state.sido === sido && !state.sigungu) select(null, null); // 다시 누르면 해제
  else select(sido, null);
});

document.getElementById("reset").onclick = () => {
  document.getElementById("search").value = "";
  state.q = "";
  select(null, null);
};

document.getElementById("search").addEventListener("input", (e) => {
  state.q = e.target.value.trim().toLowerCase();
  renderRegions();
  refreshMarkers();
});

function focusFromHash() {
  const id = decodeURIComponent((location.hash.match(/c=([^&]+)/) || [])[1] || "");
  const m = id && markers.get(id);
  if (!m) return;
  state.sido = null; state.sigungu = null; state.q = "";
  renderRegions();
  refreshMarkers();
  highlight.clearLayers();
  // 줌 16에서는 클러스터가 풀려 있으므로 바로 팝업을 열 수 있다
  map.setView(m.getLatLng(), 16, { animate: false });
  setTimeout(() => m.openPopup(), 300);
}
window.addEventListener("hashchange", focusFromHash);

(async function init() {
  const [data, sido] = await Promise.all([loadCompanies(), loadJSON("data/sido.geojson", { features: [] })]);
  sidoGeo = sido;
  items = data.items || [];

  // 시/도 경계를 옅게 깔아 둔다 (확대하면 간략화된 선이 어긋나 보이므로 숨김)
  const outline = L.geoJSON(sidoGeo, { style: { color: "#8a94a6", weight: 1, fill: false }, interactive: false });
  const toggleOutline = () => (map.getZoom() < 10 ? outline.addTo(map) : outline.remove());
  map.on("zoomend", toggleOutline);
  toggleOutline();

  for (const i of items) {
    if (i.lat == null) continue;
    const m = L.circleMarker([i.lat, i.lng], {
      radius: 5, color: "#ffffff", weight: 1, fillColor: "#e5484d", fillOpacity: 0.9,
    }).bindPopup(popupHtml(i));
    markers.set(i.id, m);
  }

  if (!items.length) {
    const div = document.createElement("div");
    div.className = "empty";
    div.innerHTML = `<div><b>아직 데이터가 없습니다.</b><br>
      README의 설정 순서대로 API End Point와 인증키를 넣고
      GitHub Actions의 <b>업체 데이터 업데이트</b>를 한 번 실행하면 업체가 표시됩니다.</div>`;
    document.getElementById("map").appendChild(div);
  }

  renderRegions();
  refreshMarkers();
  focusFromHash();
})();
