let cleanup = () => {};
let dirty = () => false;
let saving = false;
let actorName = "";
let actorKind = "human";

function element(tag, text, parent, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  if (parent) parent.append(node);
  return node;
}

function details(parent, title, text) {
  const node = element("details", undefined, parent);
  element("summary", title, node);
  element("pre", text, node);
  return node;
}

function field(parent, label, value, multiline = false) {
  const wrapper = element("label", label, parent);
  const input = element(multiline ? "textarea" : "input", undefined, wrapper);
  input.value = value;
  if (multiline) input.rows = label === "Transkription" ? 14 : 3;
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

export async function mountReview(host, object, pageIndex, onSaved) {
  unmountReview();
  const abort = new AbortController();
  cleanup = () => abort.abort();
  const alive = () => !abort.signal.aborted && host.isConnected;
  const section = element("section", undefined, host, "review-panel");
  element("h3", "Bearbeitungsstand", section);
  const states = {machine_unreviewed: "Maschinell, ungeprüft", in_review: "In Prüfung", human_verified: "Menschlich geprüft", accepted: "Abgenommen"};
  element("p", `Dokumentstatus: ${states[object.status] || "Kein menschlicher Prüfstatus dokumentiert."}`, section);
  element("p", "Eine gespeicherte Korrektur dokumentiert einen Eingriff. Formale TEI-Prüfung und fachliche Abnahme sind eigene Arbeitsschritte.", section);
  const workflow = object.workflow;
  if (workflow) {
    const history = element("details", undefined, section);
    element("summary", `TEI-Herkunft und Änderungen (${workflow.corrections})`, history);
    for (const change of workflow.changes) {
      element("p", [change.when, change.actor, change.actor_kind, change.text].filter(Boolean).join(" · "), history);
    }
  }
  const capability = element("p", "Leseansicht. Speichern ist nur über den lokalen Korrekturdienst möglich.", section, "review-message");
  if (!["127.0.0.1", "localhost"].includes(location.hostname)) return;

  async function get(path) {
    const response = await fetch(path, {signal: abort.signal, cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }
  try {
    const session = await get("api/session");
    if (!alive()) return;
    if (!session.writable) {
      capability.textContent = "Schreibzugriff gesperrt. Eine unterbrochene Transaktion muss zuerst lokal wiederhergestellt werden.";
      return;
    }
    const doc = await get(`api/documents/${encodeURIComponent(object.id)}`);
    if (!alive()) return;
    const page = doc.pages[pageIndex];
    if (!page) throw new Error("Seite nicht gefunden");
    element("p", `Diese Seite: ${states[page.review.status] || page.review.status}`, section);
    capability.textContent = "Lokaler Korrekturdienst verbunden. Gespeichert wird im Repository; es erfolgt keine Veröffentlichung.";
    for (const dependency of doc.dependencies || []) {
      const labels = {current: "Aktuell gebunden", stale: "Veraltet: neu erzeugen und prüfen", unbound: "Ohne Textbindung: Prüfung nötig", unreadable: "Nicht lesbar: Prüfung nötig"};
      element("p", `${dependency.id}: ${labels[dependency.status] || dependency.status}`, section, "dependency-status");
    }
    details(section, "Unveränderte Modelltranskription", page.transcription_raw ?? "Für diese Quelle ist keine rohe Modelltranskription hinterlegt.");
    details(section, "Transkriptionsherkunft", JSON.stringify(doc.origin, null, 2));
    const changes = element("details", undefined, section);
    element("summary", `Änderungsverlauf dieser Seite (${(page.edits || []).length})`, changes);
    for (const edit of page.edits || []) {
      const item = element("div", undefined, changes);
      element("p", `${edit.timestamp} · ${edit.actor} (${edit.actor_kind}) · ${edit.note}`, item);
      details(item, "Vorher", edit.before.transcription + "\n\nNotizen: " + edit.before.notes);
      details(item, "Nachher", edit.after.transcription + "\n\nNotizen: " + edit.after.notes);
    }
    const form = element("form", undefined, section, "review-form");
    const text = field(form, "Transkription", page.transcription, true);
    const notes = field(form, "Editorische Notizen", page.notes || "", true);
    const actor = field(form, "Bearbeiter:in (selbst angegebener Name)", actorName);
    actor.required = true;
    actor.maxLength = 200;
    const kindLabel = element("label", "Bearbeitungsrolle (selbst angegeben)", form);
    const kind = element("select", undefined, kindLabel);
    for (const [value, label] of [["human", "Mensch"], ["agent", "KI-Agent"]]) {
      const option = element("option", label, kind);
      option.value = value;
    }
    kind.value = actorKind;
    const reason = field(form, "Grund der Änderung", "", true);
    reason.required = true;
    reason.maxLength = 10000;
    dirty = () => text.value !== page.transcription || notes.value !== (page.notes || "") || reason.value !== "";
    const proposals = doc.proposals.filter(proposal => proposal.page === page.page);
    if (proposals.length) {
      const list = element("details", undefined, form);
      element("summary", `Gespeicherte Vorschläge (${proposals.length})`, list);
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
    const save = element("button", "Korrektur im Repository speichern", actions, "btn");
    save.type = "submit";
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
        const response = await fetch(`api/documents/${encodeURIComponent(object.id)}/${proposal ? "proposals" : "pages"}/${page.page}`, {
          method: "POST", signal: abort.signal,
          headers: {"Content-Type": "application/json", "X-Review-Token": session.token},
          body: JSON.stringify({version: doc.version, transcription: text.value, notes: notes.value, actor: actor.value, actor_kind: kind.value, note: reason.value})
        });
        const result = await response.json();
        if (!response.ok) {
          const prefix = response.status === 409 ? "Konflikt: Die Daten wurden inzwischen geändert. Der Entwurf bleibt hier erhalten. " : "Speichern fehlgeschlagen. Der Entwurf bleibt erhalten. ";
          throw new Error(prefix + (result.error || `HTTP ${response.status}`));
        }
        actorName = actor.value;
        actorKind = kind.value;
        dirty = () => false;
        saving = false;
        if (alive()) {
          try {
            await onSaved(proposal ? "Vorschlag separat gespeichert. Der Editionstext wurde nicht verändert." : "Korrektur gespeichert. TEI und Browserdaten wurden aktualisiert; die fachliche Prüfung ist offen.");
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
    if (alive()) capability.textContent = "Leseansicht. Der lokale Korrekturdienst ist nicht erreichbar oder die Daten sind nicht bearbeitbar.";
  }
}
