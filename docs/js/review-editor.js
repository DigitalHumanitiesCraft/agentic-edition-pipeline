import {badge, element, fetchJson} from "./dom.js";

let cleanup = () => {};
let dirty = () => false;
let saving = false;
let actorName = "";
let actorKind = "human";
// The token lives as long as the server process; a 403 drops it so a restarted server is picked up.
let token = null;

function details(parent, title, text) {
  const node = element("details", undefined, parent);
  element("summary", title, node);
  element("pre", text, node);
  return node;
}

function field(parent, label, value, rows = 0) {
  const wrapper = element("label", label, parent);
  const input = element(rows ? "textarea" : "input", undefined, wrapper);
  input.value = value;
  if (rows) input.rows = rows;
  return input;
}

export function canLeave() {
  if (saving) return false;
  return !dirty() || window.confirm("Ungespeicherte Änderungen verwerfen?");
}

export function unmountReview() {
  cleanup();
  dirty = () => false;
}

window.addEventListener("beforeunload", event => {
  if (dirty() || saving) {
    event.preventDefault();
    event.returnValue = "";
  }
});

// A loopback host alone does not mean the review server: the documented static
// previews (http.server, step 6 --serve) also bind 127.0.0.1 and have no API.
let reviewService = null;
function reviewServiceAvailable() {
  reviewService ??= fetch("index.html", {cache: "no-store"})
    .then(response => response.headers.get("X-Review-Service") === "local", () => false);
  return reviewService;
}

export async function mountReview(host, object, pageIndex, onSaved) {
  unmountReview();
  const workflow = object.workflow;
  const abort = new AbortController();
  cleanup = () => abort.abort();
  const alive = () => !abort.signal.aborted && host.isConnected;
  const local = ["127.0.0.1", "localhost"].includes(location.hostname) && await reviewServiceAvailable();
  if (!alive() || (!local && !workflow?.changes.length)) return;
  const section = element("section", undefined, host, "review-panel");
  element("h3", "Bearbeitungsstand", section);
  if (workflow?.changes.length) {
    const history = element("details", undefined, section);
    element("summary", "TEI-Herkunft und Änderungen", history);
    for (const change of workflow.changes) {
      element("p", [change.when, change.actor, change.actor_kind, change.text].filter(Boolean).join(" · "), history);
    }
  }
  if (!local) return;
  const capability = element("p", undefined, section, "review-message");

  try {
    const doc = await fetchJson(`api/documents/${encodeURIComponent(object.id)}`, {signal: abort.signal});
    if (!alive()) return;
    if (!doc.writable) {
      capability.textContent = "Schreibzugriff gesperrt. Eine unterbrochene Transaktion muss zuerst lokal wiederhergestellt werden.";
      return;
    }
    const page = doc.pages[pageIndex];
    if (!page) throw new Error("Seite nicht gefunden");
    badge(page.review.status, element("p", "Diese Seite: ", section));
    for (const dependency of doc.dependencies || []) {
      const labels = {current: "Aktuell gebunden", stale: "Veraltet: neu erzeugen und prüfen", unbound: "Ohne Textbindung: Prüfung nötig", unreadable: "Nicht lesbar: Prüfung nötig"};
      element("p", `${dependency.id}: ${labels[dependency.status] || dependency.status}`, section, "dependency-status");
    }
    details(section, "Unveränderte Modelltranskription", page.transcription_raw ?? "Für diese Quelle ist keine rohe Modelltranskription hinterlegt.");
    details(section, "Transkriptionsherkunft", JSON.stringify(doc.origin, null, 2));
    if (page.edits?.length) {
      const changes = element("details", undefined, section);
      element("summary", "Änderungsverlauf dieser Seite", changes);
      for (const edit of page.edits) {
        const item = element("div", undefined, changes);
        element("p", `${edit.timestamp} · ${edit.actor} (${edit.actor_kind}) · ${edit.note}`, item);
        details(item, "Vorher", edit.before.transcription + "\n\nNotizen: " + edit.before.notes);
        details(item, "Nachher", edit.after.transcription + "\n\nNotizen: " + edit.after.notes);
      }
    }
    const form = element("form", undefined, section, "review-form");
    const text = field(form, "Transkription", page.transcription, 14);
    const notes = field(form, "Editorische Notizen", page.notes || "", 3);
    const actor = field(form, "Bearbeiter:in (selbst angegebener Name)", actorName);
    actor.required = true;
    actor.maxLength = 200;
    const kindLabel = element("label", "Bearbeitungsrolle (selbst angegeben)", form);
    const kind = element("select", undefined, kindLabel);
    for (const [value, label] of [["human", "Mensch"], ["agent", "KI-Agent"]]) {
      element("option", label, kind).value = value;
    }
    kind.value = actorKind;
    const reason = field(form, "Grund der Änderung", "", 3);
    reason.required = true;
    reason.maxLength = 10000;
    dirty = () => text.value !== page.transcription || notes.value !== (page.notes || "") || reason.value !== "";
    const proposals = doc.proposals.filter(proposal => proposal.page === page.page);
    if (proposals.length) {
      const list = element("details", undefined, form);
      element("summary", "Gespeicherte Vorschläge", list);
      for (const proposal of proposals) {
        const current = proposal.version === doc.version;
        const item = details(list, `${proposal.actor} (${proposal.actor_kind}) · ${current ? "aktuelle Grundlage" : "veraltete Grundlage"}`, proposal.transcription + "\n\n" + proposal.note);
        const use = element("button", "In das Eingabefeld laden", item, "btn");
        use.type = "button";
        use.disabled = !current;
        use.addEventListener("click", () => {
          if ((text.value !== page.transcription || notes.value !== (page.notes || "")) && !window.confirm("Aktuellen Entwurf durch diesen Vorschlag ersetzen?")) return;
          text.value = proposal.transcription;
          notes.value = proposal.notes;
          reason.value = `Vorschlag ${proposal.id} von ${proposal.actor}: ${proposal.note}`;
          text.focus();
        });
      }
    }
    const actions = element("div", undefined, form, "review-actions");
    element("button", "Korrektur im Repository speichern", actions, "btn").type = "submit";
    const propose = element("button", "Nur als Vorschlag speichern", actions, "btn");
    propose.type = "button";
    const message = element("p", "", form, "review-message");
    message.setAttribute("role", "status");

    async function persist(proposal) {
      if (saving || !form.reportValidity()) return;
      if (!actor.value.trim() || !reason.value.trim()) {
        message.textContent = "Name und Änderungsgrund dürfen nicht leer sein.";
        return;
      }
      saving = true;
      const controls = [...form.querySelectorAll("input, textarea, select, button")];
      const disabled = controls.map(control => control.disabled);
      controls.forEach(control => { control.disabled = true; });
      message.textContent = proposal ? "Vorschlag wird gespeichert …" : "Text und TEI werden geprüft und gemeinsam gespeichert …";
      try {
        try {
          token ??= (await fetchJson("api/session", {signal: abort.signal})).token;
          await fetchJson(`api/documents/${encodeURIComponent(object.id)}/${proposal ? "proposals" : "pages"}/${page.page}`, {
            method: "POST", signal: abort.signal,
            headers: {"Content-Type": "application/json", "X-Review-Token": token},
            body: JSON.stringify({version: doc.version, transcription: text.value, notes: notes.value, actor: actor.value, actor_kind: kind.value, note: reason.value})
          });
        } catch (error) {
          if (error.status === 403) token = null;
          const prefix = error.status === 409 ? "Konflikt: Die Daten wurden inzwischen geändert." : "Nicht gespeichert.";
          throw new Error(`${prefix} Der Entwurf bleibt erhalten. ${error.message}`);
        }
        actorName = actor.value;
        actorKind = kind.value;
        dirty = () => false;
        saving = false;
        if (alive()) {
          try {
            await onSaved(proposal ? "Vorschlag separat gespeichert. Der Editionstext wurde nicht verändert." : "Korrektur gespeichert. TEI und Browserdaten wurden aktualisiert. Die fachliche Prüfung ist offen.");
          } catch (error) {
            if (alive()) message.textContent = `Gespeichert. Die Ansicht konnte nicht neu geladen werden: ${error.message}`;
          }
        }
      } catch (error) {
        if (alive()) message.textContent = error.message;
      } finally {
        saving = false;
        controls.forEach((control, index) => { control.disabled = disabled[index]; });
      }
    }
    form.addEventListener("submit", event => { event.preventDefault(); persist(false); });
    propose.addEventListener("click", () => persist(true));
  } catch (error) {
    if (alive()) capability.textContent = `Lokale Bearbeitung nicht verfügbar: ${error.message}`;
  }
}
