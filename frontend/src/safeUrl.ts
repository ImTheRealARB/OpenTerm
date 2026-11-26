/**
 * The one gate for every link that comes from the network (news items, SEC filings, alerts, pairing links).
 * A `javascript:` or `data:` URL in an href or window.open would run in the app's own origin (audit C-05), so
 * only an ALLOWLIST passes: absolute http: and https: URLs that `new URL` can parse and that name a host.
 * Everything else is null, and the caller shows plain text instead of a link. Pure, so vitest covers it.
 */
export function safeHttpUrl(u: unknown): string | null {
  if (typeof u !== "string") return null;
  let parsed: URL;
  try {
    parsed = new URL(u.trim()); // no base: relative and protocol-relative input throws
  } catch {
    return null; // not a URL at all: the caller shows text (this is the answer, not a hidden failure)
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  if (!parsed.hostname) return null;
  // The parsed form: the browser gets what we checked (control characters and odd casing are normalised away).
  return parsed.href;
}

/**
 * Opens a network-supplied link in a new tab, only when it passes `safeHttpUrl`. noopener so the page
 * cannot reach back into this window. Returns false (and says so in the console) when the link was blocked.
 */
export function openExternal(u: unknown): boolean {
  const safe = safeHttpUrl(u);
  if (!safe) {
    console.error("BLOCKED LINK: not an http(s) URL");
    return false;
  }
  window.open(safe, "_blank", "noopener,noreferrer");
  return true;
}
