// 2페이지: 엑셀형 리스트
const SIDO_ORDER = ["서울", "인천", "경기", "부산", "대구", "대전", "울산", "세종",
  "강원", "충북", "충남", "전북", "광주·전남", "경북", "경남", "제주", "미분류"];
const $ = (id) => document.getElementById(id);
const filters = { q: "", sido: "", sigungu: "" };
let table;
let items = [];

const autoTag = (field) => (cell) => {
  const d = cell.getRow().getData();
  return esc(cell.getValue() || "") + (d[field] ? '<span class="tag">자동보완</span>' : "");
};

function rowMatches(d) {
  if (filters.sido && d.sido !== filters.sido) return false;
  if (filters.sigungu && d.sigungu !== filters.sigungu) return false;
  if (filters.q) {
    const hay = `${d.name} ${d.address} ${d.phone} ${d.sido} ${d.sigungu}`.toLowerCase();
    if (!hay.includes(filters.q)) return false;
  }
  return true;
}

function fillSigungu() {
  const list = [...new Set(items.filter((i) => i.sido === filters.sido).map((i) => i.sigungu))]
    .sort((a, b) => a.localeCompare(b, "ko"));
  $("sigungu").innerHTML = '<option value="">시/군/구 전체</option>' +
    list.map((s) => `<option>${esc(s)}</option>`).join("");
  $("sigungu").disabled = !filters.sido;
}

function apply() {
  table.setFilter(rowMatches);
}

function updateCount() {
  $("count").textContent = `${table.getDataCount("active").toLocaleString()} / ${items.length.toLocaleString()}곳`;
}

function exportRows() {
  return table.getData("active").map((d) => ({
    "번호": d.no,
    "시/도": d.sido,
    "시/군/구": d.sigungu,
    "업체명": d.name,
    "주소": d.address,
    "주소 자동보완": d.address_auto ? "Y" : "",
    "전화번호": d.phone,
    "전화 자동보완": d.phone_auto ? "Y" : "",
    "매칭 키워드": d.keywords.join(", "),
    "인허가일자": d.permit_date,
    "영업상태": d.status,
    "위도": d.lat ?? "",
    "경도": d.lng ?? "",
  }));
}

function download(type) {
  const ws = XLSX.utils.json_to_sheet(exportRows());
  const today = new Date().toISOString().slice(0, 10);
  const name = `보청기업체_${filters.sido || "전국"}${filters.sigungu ? "_" + filters.sigungu : ""}_${today}`;
  if (type === "csv") {
    const csv = "﻿" + XLSX.utils.sheet_to_csv(ws); // 엑셀에서 한글이 깨지지 않도록 BOM
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = `${name}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  } else {
    ws["!cols"] = [6, 8, 14, 28, 44, 8, 16, 8, 18, 12, 10, 10, 10].map((w) => ({ wch: w }));
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "업체목록");
    XLSX.writeFile(wb, `${name}.xlsx`);
  }
}

(async function init() {
  const data = await loadCompanies();
  const order = (s) => { const i = SIDO_ORDER.indexOf(s); return i < 0 ? 99 : i; };
  items = (data.items || []).map((d, idx) => ({ ...d, no: idx + 1 }));

  const sidos = [...new Set(items.map((i) => i.sido))].sort((a, b) => order(a) - order(b));
  $("sido").innerHTML += sidos.map((s) => `<option>${esc(s)}</option>`).join("");
  fillSigungu();

  table = new Tabulator("#table", {
    data: items,
    layout: "fitDataStretch",
    height: "100%",
    placeholder: "표시할 업체가 없습니다",
    columns: [
      { title: "번호", field: "no", width: 70, hozAlign: "right" },
      { title: "시/도", field: "sido", width: 90,
        sorter: (a, b) => order(a) - order(b) },
      { title: "시/군/구", field: "sigungu", width: 130 },
      { title: "업체명", field: "name", minWidth: 180, formatter: (c) => `<b>${esc(c.getValue())}</b>` },
      { title: "주소", field: "address", minWidth: 280, formatter: autoTag("address_auto") },
      { title: "전화번호", field: "phone", width: 150, formatter: autoTag("phone_auto") },
      { title: "매칭 키워드", field: "keywords", width: 140, formatter: (c) => esc(c.getValue().join(", ")),
        sorter: (a, b) => a.join().localeCompare(b.join()) },
      { title: "인허가일자", field: "permit_date", width: 110 },
      { title: "영업상태", field: "status", width: 100 },
      { title: "지도", field: "lat", width: 70, hozAlign: "center", headerSort: false,
        formatter: (c) => (c.getValue() != null ? "📍" : '<span style="color:#aaa">없음</span>') },
    ],
  });

  table.on("dataFiltered", () => setTimeout(updateCount));
  table.on("tableBuilt", updateCount);
  table.on("rowClick", (e, row) => {
    const d = row.getData();
    if (d.lat != null) location.href = `index.html#c=${encodeURIComponent(d.id)}`;
  });

  $("search").addEventListener("input", (e) => { filters.q = e.target.value.trim().toLowerCase(); apply(); });
  $("sido").addEventListener("change", (e) => {
    filters.sido = e.target.value; filters.sigungu = ""; fillSigungu(); apply();
  });
  $("sigungu").addEventListener("change", (e) => { filters.sigungu = e.target.value; apply(); });
  $("reset").onclick = () => {
    Object.assign(filters, { q: "", sido: "", sigungu: "" });
    $("search").value = ""; $("sido").value = ""; fillSigungu(); table.clearFilter();
  };
  $("xlsx").onclick = () => download("xlsx");
  $("csv").onclick = () => download("csv");
})();
