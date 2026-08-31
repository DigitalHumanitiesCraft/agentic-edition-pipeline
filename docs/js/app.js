/* Agentic Edition Pipeline – Frontend (Vanilla JS)
   No dependencies. Hash-based routing. Works locally and on GitHub Pages. */
(function () {
  "use strict";

  var state = {
    catalog: null, projectTitle: null, currentObject: null,
    currentPage: 0, sortColumn: null, sortAsc: true
  };
  var app = document.getElementById("app");
  var titleEl = document.getElementById("project-title");

  // -- Utility --
  function debounce(fn, ms) {
    var t; return function () {
      var a = arguments, c = this;
      clearTimeout(t); t = setTimeout(function () { fn.apply(c, a); }, ms);
    };
  }
  function esc(s) { var d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
  function triggerDownload(blob, name) {
    var u = URL.createObjectURL(blob), a = document.createElement("a");
    a.href = u; a.download = name; document.body.appendChild(a);
    a.click(); document.body.removeChild(a); URL.revokeObjectURL(u);
  }

  // -- Data loading --
  function loadCatalog() {
    return fetch("data/catalog.json").then(function (r) {
      if (!r.ok) throw new Error("catalog.json not found (" + r.status + ")");
      return r.json();
    }).then(function (d) {
      if (Array.isArray(d)) { state.catalog = d; }
      else {
        // 06_build_frontend.py writes {project, objects, ...}; older data
        // used {projectTitle, items}. Accept both shapes.
        state.projectTitle = d.projectTitle || d.project || null;
        state.catalog = d.items || d.objects || [];
      }
      state.catalog.forEach(function (o) {
        if (o.page_count == null && o.pages != null) o.page_count = o.pages;
      });
      if (state.projectTitle) { titleEl.textContent = state.projectTitle; document.title = state.projectTitle; }
    });
  }
  function loadObject(id) {
    return fetch("data/" + id + ".json").then(function (r) {
      if (!r.ok) throw new Error(id + ".json not found (" + r.status + ")");
      return r.json();
    }).then(function (d) { state.currentObject = d; state.currentPage = 0; });
  }

  // -- Router --
  function getRoute() {
    var h = window.location.hash.replace(/^#\/?/, "");
    if (!h || h === "catalog") return { view: "catalog" };
    var m = h.match(/^viewer\/(.+)$/);
    return m ? { view: "viewer", id: decodeURIComponent(m[1]) } : { view: "catalog" };
  }
  function navigate() {
    var route = getRoute();
    updateActiveNav(route.view);
    if (route.view === "catalog") { renderCatalog(); }
    else if (route.view === "viewer") {
      app.innerHTML = "<p>Lade&hellip;</p>";
      loadObject(route.id).then(function () { renderViewer(route.id); })
        .catch(function (e) { app.innerHTML = '<p class="catalog-empty">Fehler: ' + esc(e.message) + "</p>"; });
    }
  }
  function updateActiveNav(view) {
    document.querySelectorAll(".nav-link").forEach(function (l) {
      var match = l.dataset.view === view || (view === "viewer" && l.dataset.view === "catalog");
      l.classList.toggle("active", match);
    });
  }

  // -- Catalog view --
  function renderCatalog() {
    if (!state.catalog) { app.innerHTML = '<p class="catalog-empty">Kein Katalog geladen.</p>'; return; }
    var cols = [
      { key: "title", label: "Titel" }, { key: "signature", label: "Signatur" },
      { key: "date", label: "Datum" },
      { key: "language", label: "Sprache" }, { key: "page_count", label: "Seiten" },
      { key: "status", label: "Status" }
    ];
    var html = '<input type="search" class="search-input" placeholder="Suche nach Titel oder Datum&hellip;" aria-label="Katalog durchsuchen">';
    html += '<table class="catalog-table"><thead><tr>';
    cols.forEach(function (c) {
      var arrow = state.sortColumn === c.key ? (state.sortAsc ? " &#9650;" : " &#9660;") : "";
      html += '<th data-sort="' + c.key + '">' + c.label + '<span class="sort-arrow">' + arrow + "</span></th>";
    });
    html += "</tr></thead><tbody>";
    var items = sortItems(state.catalog.slice());
    if (!items.length) { html += '<tr><td colspan="6" class="catalog-empty">Keine Eintr&auml;ge.</td></tr>'; }
    else { items.forEach(function (it) {
      html += "<tr>";
      html += '<td><a href="#viewer/' + encodeURIComponent(it.id) + '">' + esc(it.title || it.id) + "</a></td>";
      html += "<td>" + esc(it.signature || "") + "</td><td>" + esc(it.date || "") + "</td><td>" + esc(it.language || "") + "</td>";
      html += "<td>" + (it.page_count != null ? it.page_count : "") + "</td>";
      html += "<td>" + badgeHtml(it.status) + "</td></tr>";
    }); }
    html += "</tbody></table>";
    app.innerHTML = html;
    var input = app.querySelector(".search-input");
    input.addEventListener("input", debounce(function () { filterCatalog(input.value); }, 200));
    app.querySelectorAll("th[data-sort]").forEach(function (th) {
      th.addEventListener("click", function () {
        var k = th.dataset.sort;
        if (state.sortColumn === k) state.sortAsc = !state.sortAsc;
        else { state.sortColumn = k; state.sortAsc = true; }
        var q = input.value;
        renderCatalog();
        var ni = app.querySelector(".search-input");
        if (ni && q) { ni.value = q; filterCatalog(q); }
      });
    });
  }
  function sortItems(items) {
    if (!state.sortColumn) return items;
    var k = state.sortColumn, d = state.sortAsc ? 1 : -1;
    return items.sort(function (a, b) {
      var va = a[k] != null ? a[k] : "", vb = b[k] != null ? b[k] : "";
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * d;
      return String(va).localeCompare(String(vb), "de") * d;
    });
  }
  function badgeHtml(s) {
    if (!s) return "";
    var labels = {
      machine_unreviewed: "Maschinell, ungepr&uuml;ft",
      in_review: "In Pr&uuml;fung",
      human_verified: "Menschlich gepr&uuml;ft",
      accepted: "Abgenommen",
      confident: "Automatisch unauff&auml;llig",
      needs_review: "Automatische Pr&uuml;fung n&ouml;tig",
      problematic: "Automatischer Problembefund"
    };
    return '<span class="badge badge-' + s.replace(/\s+/g, "_") + '">' +
      (labels[s] || esc(s)) + "</span>";
  }
  function filterCatalog(q) {
    q = q.toLowerCase();
    app.querySelectorAll(".catalog-table tbody tr").forEach(function (r) {
      r.style.display = r.textContent.toLowerCase().indexOf(q) !== -1 ? "" : "none";
    });
  }

  // -- Viewer --
  function renderViewer(objectId) {
    var obj = state.currentObject;
    if (!obj) return;
    var pages = obj.pages || [], has = pages.length > 0;
    var html = '<div class="viewer-header"><h2>' + esc(obj.title || objectId) + "</h2>";
    html += badgeHtml(obj.status);
    html += '<div class="viewer-actions">';
    html += '<button class="btn" id="btn-tei">TEI-XML herunterladen</button>';
    html += '<button class="btn" id="btn-txt">Plaintext exportieren</button>';
    html += '<a href="#catalog" class="btn">Zur&uuml;ck</a></div></div>';
    if (has) {
      html += '<div class="viewer-panels">';
      html += '<div class="panel"><div class="panel-label">Faksimile</div><div class="panel-image" id="img-panel"></div></div>';
      html += '<div class="panel"><div class="panel-label">Text</div><div class="panel-text" id="txt-panel"></div></div>';
      html += '</div><div class="page-nav">';
      html += '<button id="btn-prev" aria-label="Vorherige Seite">Zur&uuml;ck</button>';
      html += '<span class="page-counter" id="pg-count"></span>';
      html += '<button id="btn-next" aria-label="N&auml;chste Seite">Weiter</button></div>';
    } else { html += '<p class="catalog-empty">Keine Seiten vorhanden.</p>'; }
    app.innerHTML = html;
    if (has) {
      showPage();
      document.getElementById("btn-prev").addEventListener("click", function () { navigatePage(-1); });
      document.getElementById("btn-next").addEventListener("click", function () { navigatePage(1); });
    }
    document.getElementById("btn-tei").addEventListener("click", function () { downloadTEI(objectId); });
    document.getElementById("btn-txt").addEventListener("click", function () { exportPlaintext(objectId); });
  }
  function showPage() {
    var pages = state.currentObject.pages || [], pg = pages[state.currentPage];
    if (!pg) return;
    var ip = document.getElementById("img-panel"), tp = document.getElementById("txt-panel");
    var ct = document.getElementById("pg-count");
    var label = pg.label || String(state.currentPage + 1);
    if (pg.image) ip.innerHTML = '<img src="' + esc(pg.image) + '" alt="Faksimile Seite ' + esc(label) + '">';
    else ip.innerHTML = '<span class="no-image">Kein Bild verf&uuml;gbar</span>';
    tp.textContent = pg.text || "(kein Text)";
    ct.textContent = "Seite " + label + " (" + (state.currentPage + 1) + " von " + pages.length + ")";
    document.getElementById("btn-prev").disabled = state.currentPage === 0;
    document.getElementById("btn-next").disabled = state.currentPage >= pages.length - 1;
  }
  function navigatePage(delta) {
    var pages = state.currentObject.pages || [], n = state.currentPage + delta;
    if (n < 0 || n >= pages.length) return;
    state.currentPage = n; showPage();
  }

  // -- Downloads --
  function downloadTEI(id) {
    var a = document.createElement("a");
    a.href = "tei/" + encodeURIComponent(id) + ".xml"; a.download = id + ".xml";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  }
  function exportPlaintext(id) {
    var obj = state.currentObject;
    if (!obj || !obj.pages) return;
    var txt = obj.pages.map(function (p, i) {
      return "--- Seite " + (p.label || (i + 1)) + " ---\n" + (p.text || "");
    }).join("\n\n");
    triggerDownload(new Blob([txt], { type: "text/plain;charset=utf-8" }), id + ".txt");
  }

  // -- Init --
  function init() {
    loadCatalog().then(navigate).catch(function (e) {
      app.innerHTML = '<p class="catalog-empty">Katalog konnte nicht geladen werden.<br><small>' +
        esc(e.message) + '</small></p><p class="catalog-empty"><small>Stellen Sie sicher, dass ' +
        "<code>docs/data/catalog.json</code> existiert.</small></p>";
    });
    window.addEventListener("hashchange", navigate);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
