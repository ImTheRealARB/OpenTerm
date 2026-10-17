/** The sign-up link a row may open: web links only (the value comes from the backend). */
export function apiKeysSignup(url: string | null | undefined): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null;
}
