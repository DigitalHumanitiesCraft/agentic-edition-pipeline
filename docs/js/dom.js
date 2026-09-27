// Imported TEI and review data are untrusted, so data only ever reaches the
// page through textContent and property assignment, never through HTML strings.
export function element(tag, text, parent, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  if (parent) parent.append(node);
  return node;
}

export async function fetchJson(url, options = {}) {
  const response = await fetch(url, {cache: "no-store", ...options});
  // Error bodies are not guaranteed to be JSON (for example a plain 503 page).
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body.error || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return body;
}

const STATUS_LABELS = {
  machine_unreviewed: "Maschinell, ungeprüft",
  in_review: "In Prüfung",
  human_verified: "Menschlich geprüft",
  accepted: "Abgenommen"
};

export function badge(status, parent) {
  if (!status) return null;
  const known = Object.hasOwn(STATUS_LABELS, status);
  return element("span", known ? STATUS_LABELS[status] : status, parent, known ? `badge badge-${status}` : "badge");
}
