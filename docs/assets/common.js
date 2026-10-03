// 두 페이지가 같이 쓰는 데이터 로딩·상단 바
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

async function loadJSON(path, fallback) {
  try {
    const r = await fetch(path, { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch (e) {
    return fallback;
  }
}

async function loadCompanies() {
  const [data, changes] = await Promise.all([
    loadJSON("data/companies.json", { items: [] }),
    loadJSON("data/changes.json", []),
  ]);
  renderMeta(data, changes);
  return data;
}

function renderMeta(data, changes) {
  const meta = document.getElementById("meta");
  if (!meta) return;
  const parts = [`업체 <b>${(data.count ?? data.items.length).toLocaleString()}</b>곳`];
  if (data.located != null && data.located < data.count) {
    parts.push(`위치없음 ${data.count - data.located}곳`);
  }
  parts.push(`업데이트 ${esc(data.updated_at || "-")}`);
  meta.innerHTML = parts.map((p) => `<span>${p}</span>`).join("");
  if (changes.length) {
    const c = changes[0];
    const btn = document.createElement("span");
    btn.className = "changes";
    btn.textContent = `최근 변경(${c.date.slice(5, 10)}): 신규 ${c.added.length} · 제외 ${c.removed.length}`;
    btn.onclick = () => showChanges(changes);
    meta.appendChild(btn);
  }
}

function showChanges(changes) {
  let dlg = document.getElementById("changes-dialog");
  if (!dlg) {
    dlg = document.createElement("dialog");
    dlg.id = "changes-dialog";
    document.body.appendChild(dlg);
  }
  const line = (i, cls, sign) =>
    `<div class="${cls}">${sign} ${esc(i.name)} <span class="n">(${esc(i.sido)} ${esc(i.sigungu)})</span></div>`;
  dlg.innerHTML = `<header><b>변경 이력</b><button class="btn" onclick="this.closest('dialog').close()">닫기</button></header>
    <div class="body">${changes.map((c) => `<h4>${esc(c.date)}</h4>
      ${c.added.map((i) => line(i, "plus", "+")).join("")}
      ${c.removed.map((i) => line(i, "minus", "−")).join("")}`).join("")}</div>`;
  dlg.showModal();
}
