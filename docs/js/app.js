// Hash-routed static viewer, served by GitHub Pages or the local review server.
import {badge, element, fetchJson} from "./dom.js";
import {canLeave, mountReview, unmountReview} from "./review-editor.js";

const state = {catalog: null, currentObject: null, currentPage: 0, sortColumn: null, sortAsc: true};
const app = document.getElementById("app");
const notice = document.getElementById("notice");
const titleEl = document.getElementById("project-title");
const COLUMNS = [
  {key: "title", label: "Titel"}, {key: "signature", label: "Signatur"},
  {key: "date", label: "Datum"}, {key: "language", label: "Sprache"},
  {key: "page_count", label: "Seiten"}, {key: "status", label: "Status"}
];
let routeVersion = 0;
let currentHash = location.hash;
let viewer = null;

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function showMessage(text) {
  app.replaceChildren();
  element("p", text, app, "catalog-empty");
}

// TEI graphic/@url is untrusted, so only web URLs reach img.src.
function imageUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(value, document.baseURI);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

async function loadCatalog() {
  const data = await fetchJson("data/catalog.json");
  if (!Array.isArray(data.objects)) throw new Error("catalog.json enthält keine Objektliste");
  state.catalog = data.objects;
  if (data.project) {
    titleEl.textContent = data.project;
    document.title = data.project;
  }
}

function loadObject(id) {
  return fetchJson("data/" + encodeURIComponent(id) + ".json");
}

function getRoute() {
  const h = location.hash.replace(/^#\/?/, "");
  const m = h.match(/^viewer\/(.+)$/);
  return m ? {view: "viewer", id: decodeURIComponent(m[1])} : {view: "catalog"};
}

function navigate() {
  if (!canLeave()) {
    history.replaceState(null, "", currentHash || "#catalog");
    return;
  }
  unmountReview();
  currentHash = location.hash;
  notice.textContent = "";
  const version = ++routeVersion;
  const route = getRoute();
  updateActiveNav(route.view);
  if (route.view === "catalog") {
    renderCatalog();
    return;
  }
  showMessage("Lade …");
  loadObject(route.id).then(object => {
    if (version !== routeVersion) return;
    state.currentObject = object;
    state.currentPage = 0;
    renderViewer(route.id);
  }).catch(error => {
    if (version === routeVersion) showMessage("Fehler: " + error.message);
  });
}

function updateActiveNav(view) {
  document.querySelectorAll(".nav-link").forEach(link => {
    link.classList.toggle("active", link.dataset.view === view || (view === "viewer" && link.dataset.view === "catalog"));
  });
}

function renderCatalog() {
  if (!state.catalog) {
    showMessage("Kein Katalog geladen.");
    return;
  }
  app.replaceChildren();
  const input = element("input", undefined, app, "search-input");
  input.type = "search";
  input.placeholder = "Suche nach Titel oder Datum …";
  input.setAttribute("aria-label", "Katalog durchsuchen");
  const table = element("table", undefined, element("div", undefined, app, "table-scroll"), "catalog-table");
  const headRow = element("tr", undefined, element("thead", undefined, table));
  const tbody = element("tbody", undefined, table);
  const headers = COLUMNS.map(column => {
    const th = element("th", undefined, headRow);
    th.scope = "col";
    const button = element("button", column.label, th, "sort-button");
    button.type = "button";
    element("span", "", button, "sort-arrow").setAttribute("aria-hidden", "true");
    button.addEventListener("click", () => {
      if (state.sortColumn === column.key) state.sortAsc = !state.sortAsc;
      else {
        state.sortColumn = column.key;
        state.sortAsc = true;
      }
      renderRows();
    });
    return th;
  });

  function renderRows() {
    COLUMNS.forEach((column, index) => {
      const th = headers[index];
      const sorted = state.sortColumn === column.key;
      if (sorted) th.setAttribute("aria-sort", state.sortAsc ? "ascending" : "descending");
      else th.removeAttribute("aria-sort");
      th.querySelector(".sort-arrow").textContent = sorted ? (state.sortAsc ? "▲" : "▼") : "";
    });
    tbody.replaceChildren();
    const items = sortItems(state.catalog.slice());
    if (!items.length) {
      element("td", "Keine Einträge.", element("tr", undefined, tbody), "catalog-empty").colSpan = COLUMNS.length;
    }
    for (const item of items) {
      const row = element("tr", undefined, tbody);
      element("a", item.title || item.id, element("td", undefined, row)).href = "#viewer/" + encodeURIComponent(item.id);
      for (const key of ["signature", "date", "language", "page_count"]) element("td", item[key] ?? "", row);
      badge(item.status, element("td", undefined, row));
    }
    filterCatalog(input.value);
  }

  input.addEventListener("input", debounce(() => filterCatalog(input.value), 200));
  renderRows();
}

function sortItems(items) {
  if (!state.sortColumn) return items;
  const k = state.sortColumn;
  const d = state.sortAsc ? 1 : -1;
  return items.sort((a, b) => {
    const va = a[k] ?? "";
    const vb = b[k] ?? "";
    if (typeof va === "number" && typeof vb === "number") return (va - vb) * d;
    return String(va).localeCompare(String(vb), "de") * d;
  });
}

function filterCatalog(q) {
  q = q.toLowerCase();
  app.querySelectorAll(".catalog-table tbody tr").forEach(r => {
    r.hidden = r.textContent.toLowerCase().indexOf(q) === -1;
  });
}

function renderViewer(id) {
  const obj = state.currentObject;
  if (!obj) return;
  const pages = obj.pages || [];
  app.replaceChildren();
  viewer = null;
  const header = element("div", undefined, app, "viewer-header");
  element("h2", obj.title || id, header);
  badge(obj.status, header);
  const actions = element("div", undefined, header, "viewer-actions");
  const a = element("a", "TEI-XML herunterladen", actions, "btn");
  a.href = "tei/" + encodeURIComponent(id) + ".xml";
  a.download = id + ".xml";
  const plaintext = element("button", "Plaintext exportieren", actions, "btn");
  plaintext.type = "button";
  plaintext.addEventListener("click", () => exportPlaintext(id));
  element("a", "Zum Katalog", actions, "btn").href = "#catalog";
  if (!pages.length) {
    element("p", "Keine Seiten vorhanden.", app, "catalog-empty");
    return;
  }
  const panels = element("div", undefined, app, "viewer-panels");
  const imagePanel = element("section", undefined, panels, "panel");
  imagePanel.setAttribute("aria-label", "Faksimile");
  const textPanel = element("section", undefined, panels, "panel");
  textPanel.setAttribute("aria-label", "Text");
  const pageNav = element("div", undefined, app, "page-nav");
  viewer = {
    image: element("div", undefined, imagePanel, "panel-image"),
    text: element("div", undefined, textPanel, "panel-text"),
    review: element("div", undefined, textPanel),
    prev: element("button", "Vorherige Seite", pageNav),
    counter: element("span", undefined, pageNav, "page-counter"),
    next: element("button", "Nächste Seite", pageNav)
  };
  viewer.prev.type = "button";
  viewer.next.type = "button";
  viewer.prev.addEventListener("click", () => navigatePage(-1));
  viewer.next.addEventListener("click", () => navigatePage(1));
  showPage();
}

function showPage() {
  const pages = state.currentObject.pages;
  const pg = pages[state.currentPage];
  const label = pg.label || String(state.currentPage + 1);
  const src = imageUrl(pg.image);
  if (src) {
    const img = element("img");
    img.src = src;
    img.alt = "Faksimile Seite " + label;
    viewer.image.replaceChildren(img);
  } else {
    viewer.image.replaceChildren(element("span", pg.image ? "Bildadresse nicht zulässig" : "Kein Bild verfügbar", undefined, "no-image"));
  }
  viewer.text.textContent = pg.text || "(kein Text)";
  viewer.counter.textContent = `Seite ${label} (${state.currentPage + 1} von ${pages.length})`;
  viewer.prev.disabled = state.currentPage === 0;
  viewer.next.disabled = state.currentPage >= pages.length - 1;
  viewer.review.replaceChildren();
  mountReview(viewer.review, state.currentObject, state.currentPage, reloadAfterSave);
}

async function reloadAfterSave(text) {
  const pageIndex = state.currentPage;
  const id = state.currentObject.id;
  state.currentObject = await loadObject(id);
  await loadCatalog();
  state.currentPage = pageIndex;
  renderViewer(id);
  notice.textContent = text;
}

function navigatePage(delta) {
  const n = state.currentPage + delta;
  if (n < 0 || n >= state.currentObject.pages.length || !canLeave()) return;
  notice.textContent = "";
  state.currentPage = n;
  showPage();
}

function exportPlaintext(id) {
  const txt = state.currentObject.pages
    .map((p, i) => `--- Seite ${p.label || i + 1} ---\n${p.text || ""}`)
    .join("\n\n");
  const url = URL.createObjectURL(new Blob([txt], {type: "text/plain;charset=utf-8"}));
  const link = element("a", undefined, document.body);
  link.href = url;
  link.download = id + ".txt";
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

loadCatalog().then(navigate).catch(error => showMessage("Katalog konnte nicht geladen werden: " + error.message));
window.addEventListener("hashchange", navigate);
