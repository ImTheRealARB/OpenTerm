/** Phase 11: what the APIKEYS panel shows while a key is typed. Never more than the last 4 characters. */
export function maskKey(v: string): string {
  if (!v) return "";
  if (v.length <= 4) return "•".repeat(v.length);
  return "••••" + v.slice(-4);
}
