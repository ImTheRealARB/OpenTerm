// Run: node --test scripts/benchEnv.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { benchChildEnv } from "./benchEnv.mjs";

test("strips credentials, keeps the rest, extra wins", () => {
  const out = benchChildEnv(
    { OPENROUTER_API_KEY: "real", ALPACA_SECRET_KEY: "s", TRADIER_TOKEN: "t", SMTP_HOST: "h", PATH: "/bin", SEC_USER_AGENT: "ua" },
    { OPENTERM_FIXTURES: "1" },
  );
  assert.deepEqual(out, { PATH: "/bin", SEC_USER_AGENT: "ua", OPENTERM_FIXTURES: "1" });
});
