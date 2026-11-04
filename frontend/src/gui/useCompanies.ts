import { useEffect, useState } from "react";
import type { CompanyHit } from "./companySearch";

/**
 * Company suggestions for a search box. Nothing is fetched until `enabled` (the box has focus) and the text is at least
 * 2 characters, so startup never pays for the 1 MB stock universe. The data module is loaded with `import()` on first use.
 * Typing is debounced by 120 ms so each keystroke does not re-scan the universe.
 */
export function useCompanies(query: string, enabled: boolean): CompanyHit[] {
  const [hits, setHits] = useState<CompanyHit[]>([]);
  useEffect(() => {
    const q = query.trim();
    if (!enabled || q.length < 2) {
      setHits([]);
      return;
    }
    let current = true; // set false when the text changes, so a slow answer for an old query is dropped
    const timer = setTimeout(() => {
      import("./suggestData")
        .then((m) => m.suggest(q, (h) => current && setHits(h), () => current))
        .catch(() => {});
    }, 120);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [query, enabled]);
  return hits;
}
