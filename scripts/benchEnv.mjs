// Child environment for the servers the bench spawns.
//
// Why: the key store treats a key found in the environment as "env locked" (HTTP 409 on write), so a real
// OPENROUTER_API_KEY in the shell made the bench's own fake-key PUT fail and the run crashed. A real key would
// also let a bench probe reach a paid provider. The bench must measure the same app on every machine, so every
// credential-like variable (the names in backend/openterm/keys.py) is removed from the inherited environment.
// Budgets are untouched: this only changes what the servers can see, not what is measured or gated.
const SECRET_NAME = /(_KEY|_KEY_ID|_SECRET|_SECRET_KEY|_TOKEN|_PASSWORD|_CLIENT_ID|_CLIENT_SECRET)$/;
const KEYED_EXTRA = /^(SMTP_|ALERT_WEBHOOK_URL$|SEARXNG_URL$)/;

/** Returns a copy of `base` without credential variables, then applies `extra` on top. */
export function benchChildEnv(base, extra = {}) {
  const clean = {};
  for (const [k, v] of Object.entries(base)) {
    if (SECRET_NAME.test(k.toUpperCase()) || KEYED_EXTRA.test(k.toUpperCase())) continue;
    clean[k] = v;
  }
  return { ...clean, ...extra };
}
