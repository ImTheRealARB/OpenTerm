/**
 * `SRC=<name>` in the command line: pin the data source for this one command (AAPL GP 5Y SRC=NASDAQ, AAPL Q SRC=KITE).
 * Pure and tiny (the parser imports it), so it adds nothing to the startup bundle. The name list for autocomplete comes from
 * GET /api/sources (`net/sources.ts`); the backend is the judge of whether a source exists and can serve the command.
 */

export const SRC_RE = /^SRC=(.*)$/i;
/** Functions whose own arguments already use `SRC=` (PRED SRC=POLY|KALSHI|ALL picks a market, not a data provider). */
export const OWN_SRC_FUNCTIONS = new Set(["PRED"]);
const NAME_RE = /^[A-Za-z][A-Za-z0-9_]{0,39}$/;

/**
 * Takes the `SRC=` token out of a command's words. The first word is never a pin. Returns the remaining words and the
 * source (lower case), or an error text for an empty name, a bad name or a second pin.
 */
export function takeSource(tokens: string[]): { tokens: string[]; source?: string } | { error: string } {
  let source: string | undefined;
  const rest: string[] = [];
  if (tokens[0] && OWN_SRC_FUNCTIONS.has(tokens[0].toUpperCase())) return { tokens };
  for (const [i, t] of tokens.entries()) {
    const m = i > 0 ? SRC_RE.exec(t) : null;
    if (!m) {
      rest.push(t);
      continue;
    }
    if (source !== undefined) return { error: "ONE SRC= PER COMMAND" };
    if (!m[1]) return { error: "SRC= NEEDS A SOURCE NAME, E.G. SRC=NASDAQ (SEE SOURCES)" };
    if (!NAME_RE.test(m[1])) return { error: `BAD SOURCE NAME: ${m[1].toUpperCase().slice(0, 40)}` };
    source = m[1].toLowerCase();
  }
  return { tokens: rest, source };
}

export interface SourceHit {
  name: string;
  label: string;
}

/** The partial name when the last word of `text` is `SRC=...` (and is not the first word), else null. */
export function srcToken(text: string): string | null {
  const words = text.trimStart().split(/\s+/);
  if (OWN_SRC_FUNCTIONS.has(words[0].toUpperCase())) return null;
  const m = words.length > 1 ? SRC_RE.exec(words[words.length - 1]) : null;
  return m ? m[1] : null;
}

/** Sources that start with, then contain, what was typed; at most `max`. */
export function matchSources(partial: string, all: SourceHit[], max = 10): SourceHit[] {
  const p = partial.toLowerCase();
  const starts = all.filter((s) => s.name.startsWith(p));
  const has = all.filter((s) => !s.name.startsWith(p) && (s.name.includes(p) || s.label.toLowerCase().includes(p)));
  return [...starts, ...has].slice(0, max);
}
