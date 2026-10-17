/** Shared list navigation for DOM lists (LAYOUT, WL index, SETTINGS): j k ↑ ↓ g G Home End PgUp PgDn. */
export function listNav(key: string, i: number, n: number, page = 10): number | null {
  if (n <= 0) return null;
  const clamp = (v: number) => Math.max(0, Math.min(n - 1, v));
  switch (key) {
    case "j":
    case "ArrowDown":
      return clamp(i + 1);
    case "k":
    case "ArrowUp":
      return clamp(i - 1);
    case "g":
    case "Home":
      return 0;
    case "G":
    case "End":
      return n - 1;
    case "PageDown":
      return clamp(i + page);
    case "PageUp":
      return clamp(i - page);
  }
  return null;
}
