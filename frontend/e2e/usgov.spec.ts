import { expect, test } from "@playwright/test";
import { env, exportCsv, panel, run, setup } from "./p19util";

// USASP, FEDREG, FEC and CONGRESS end-to-end tests (mocked routes only, no network). Every name and number below is MADE-UP test data in the shape the
// backend returns. The real shapes of USASP and FEDREG are recorded in backend/tests/fixtures/usasp_real_*.json and fedreg_real_*.json; FEC and CONGRESS
// shapes are doc-shaped (no key was available), see backend/tests/fixtures/*_docshape.json.

const USASP_NOTE = "AMOUNTS ARE US DOLLARS OBLIGATED (COMMITTED BY CONTRACT OR GRANT), NOT PAYMENTS AND NOT THE RECIPIENT'S REVENUE.";
const KEYWORD = {
  mode: "KEYWORD", query: "test corp", window: "FY2025 TO 2026-11-05", award_kind: "CONTRACTS", note: USASP_NOTE, notes: [],
  recipients: [{ name: "TEST CORP", uei: "UEI000000001", amount: 1_500_000_000 }, { name: "TEST CORP SERVICES", uei: null, amount: 40_000_000 }],
  recipients_total: 1_540_000_000,
  awards: [{ award_id: "TST0001", recipient: "TEST CORP", amount: 2_000_000_000, agency: "Test Department", start: "2020-01-01", end: "2030-01-01", description: "A TEST CONTRACT" }],
};
const AGENCIES = {
  mode: "AGENCY", window: "FY2025 TO 2026-11-05", award_kind: "ALL AWARD TYPES", note: "ENTER OPENS THE AGENCY'S TOP CONTRACT RECIPIENTS.",
  agencies: [{ name: "Test Department of Things", code: "TDT", amount: 9_000_000_000_000 }, { name: "Other Agency", code: "OTH", amount: 5_000_000 }],
};

test("USASP: a keyword lists recipients, V switches to awards, amounts are labelled obligated, E exports", async ({ page }) => {
  const { errors } = await setup(page);
  const asked: string[] = [];
  await page.route("**/api/world/usasp?**", (r) => {
    asked.push(new URL(r.request().url()).searchParams.get("q") ?? "");
    return r.fulfill({ json: env(KEYWORD, { source: "USASPENDING.GOV" }) });
  });
  await run(page, "USASP test corp");
  const p = panel(page);
  await expect(p).toContainText("US FEDERAL SPENDING · TEST CORP");
  await expect(p).toContainText("USD OBLIGATED");
  await expect(p).toContainText("TOP 2 RECIPIENTS TOTAL $1.54B");
  await expect(p).toContainText("NOT PAYMENTS");
  await expect(p.locator(".sr")).toContainText("TEST CORP");
  await expect(p.locator(".sr")).toContainText("$1.50B");
  await page.keyboard.press("v");
  await expect(p).toContainText("AWARDS");
  await expect(p.locator(".sr")).toContainText("TST0001");
  const csv = await exportCsv(page);
  expect(csv.name).toContain("USASP_AWARDS");
  expect(csv.text).toContain("TST0001");
  expect(asked).toEqual(["test corp"]);
  expect(errors).toEqual([]);
});

test("USASP: the agency view lists agencies and Enter opens that agency's recipients", async ({ page }) => {
  const { errors } = await setup(page);
  const asked: string[] = [];
  await page.route("**/api/world/usasp?**", (r) => {
    const q = new URL(r.request().url()).searchParams.get("q") ?? "";
    asked.push(q);
    return r.fulfill({ json: env(q.startsWith("AGENCY:") ? { ...KEYWORD, mode: "AGENCY_RECIPIENTS", agency: q.slice(7) } : AGENCIES) });
  });
  await run(page, "USASP AGENCY");
  const p = panel(page);
  await expect(p).toContainText("TOP AGENCIES");
  await expect(p.locator(".sr")).toContainText("TDT");
  await expect(p.locator(".sr")).toContainText("$9.00T");
  await page.keyboard.press("Enter");
  await expect(p).toContainText("TEST DEPARTMENT OF THINGS");
  await expect.poll(() => asked).toEqual(["AGENCY", "AGENCY:Test Department of Things"]);
  expect(errors).toEqual([]);
});

test("USASP: no match says so instead of showing an empty table", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/usasp?**", (r) => r.fulfill({ json: env({ ...KEYWORD, recipients: [], recipients_total: null, awards: [] }) }));
  await run(page, "USASP zzqx");
  await expect(panel(page)).toContainText("NO AWARDS MATCH IN THIS WINDOW");
  expect(errors).toEqual([]);
});

const FEDREG = {
  query: "chips", type: null, total: 1234, shown: 2, note: "US FEDERAL REGISTER DOCUMENTS AS PUBLISHED, NEWEST FIRST. THE ABSTRACT IS THE AGENCY'S OWN SUMMARY, NOT OPENTERM'S.",
  items: [
    { number: "2026-90001", title: "Test Rule on Chips", type: "Rule", agencies: ["Test Agency", "Second Agency"], date: "2026-11-05", abstract: "A TEST ABSTRACT.", url: "https://www.federalregister.gov/documents/test" },
    { number: "2026-90002", title: "Test Notice", type: "Notice", agencies: ["Test Agency"], date: "2026-11-04", abstract: null, url: null },
  ],
};

test("FEDREG: documents list newest first, Enter shows the agency's abstract, a missing abstract is said", async ({ page }) => {
  const { errors } = await setup(page);
  const asked: string[] = [];
  await page.route("**/api/world/fedreg?**", (r) => {
    asked.push(new URL(r.request().url()).searchParams.get("q") ?? "");
    return r.fulfill({ json: env(FEDREG, { source: "FEDERALREGISTER.GOV" }) });
  });
  await run(page, "FEDREG rule chips");
  const p = panel(page);
  await expect(p).toContainText("FEDERAL REGISTER · CHIPS");
  await expect(p).toContainText("1,234 DOCUMENTS MATCH · NEWEST 2 SHOWN");
  await expect(p.locator(".sr")).toContainText("Test Rule on Chips");
  await page.keyboard.press("Enter");
  await expect(p.getByTestId("fedreg-detail")).toContainText("A TEST ABSTRACT.");
  await expect(p.getByTestId("fedreg-detail")).toContainText("Test Agency, Second Agency");
  await page.keyboard.press("j");
  await page.keyboard.press("Enter");
  await expect(p.getByTestId("fedreg-detail")).toContainText("THE AGENCY GAVE NO ABSTRACT");
  const csv = await exportCsv(page);
  expect(csv.text).toContain("2026-90002");
  expect(asked).toEqual(["rule chips"]);
  expect(errors).toEqual([]);
});

const FEC_SEARCH = {
  mode: "SEARCH", query: "example", notes: [], note: "FIGURES ARE US DOLLARS AS REPORTED TO THE FEC ON FILINGS: SELF-REPORTED BY CAMPAIGNS AND COMMITTEES.",
  items: [
    { kind: "CANDIDATE", id: "H0ZZ00001", name: "EXAMPLE, TEST A", party: "INDEPENDENT", office: "House", state: "ZZ", district: "01", last_year: 2026 },
    { kind: "COMMITTEE", id: "C00000001", name: "EXAMPLE TEST FOR CONGRESS", party: null, office: "House", state: "ZZ", district: null, last_year: 2026 },
  ],
};
const FEC_ENTITY = {
  mode: "CANDIDATE", id: "H0ZZ00001", name: "EXAMPLE, TEST A", note: FEC_SEARCH.note,
  cycles: [
    { cycle: 2026, receipts: 1_250_000.5, disbursements: 980_000.25, cash: 270_000.25, debts: 0, individual: 950_000.5, covered_to: "2026-09-30" },
    { cycle: 2024, receipts: 2_100_000, disbursements: 2_050_000, cash: 5_000, debts: 10_000, individual: 1_800_000, covered_to: "2024-12-31" },
  ],
  latest: { cycle: 2026, receipts: 1_250_000.5, disbursements: 980_000.25, cash: 270_000.25, debts: 0, individual: 950_000.5, covered_to: "2026-09-30" },
};

test("FEC: a search lists candidates and committees and Enter opens the totals of the highlighted one", async ({ page }) => {
  const { errors } = await setup(page);
  const asked: string[] = [];
  await page.route("**/api/world/fec?**", (r) => {
    const q = new URL(r.request().url()).searchParams.get("q") ?? "";
    asked.push(q);
    return r.fulfill({ json: env(/^H\w+\d$/.test(q) ? FEC_ENTITY : FEC_SEARCH, { source: "openfec (doc-shaped fixture, NOT A RECORDING)" }) });
  });
  await run(page, "FEC example");
  const p = panel(page);
  await expect(p).toContainText("SELF-REPORTED");
  await expect(p.locator(".sr")).toContainText("H0ZZ00001");
  await page.keyboard.press("Enter");
  await expect(p.getByTestId("fec-summary")).toContainText("EXAMPLE, TEST A");
  await expect(p.getByTestId("fec-summary")).toContainText("LATEST CYCLE 2026 · RECEIPTS $1.25M");
  await expect(p.locator(".sr")).toContainText("2026");
  const csv = await exportCsv(page);
  expect(csv.name).toContain("FEC_H0ZZ00001");
  await expect.poll(() => asked).toEqual(["example", "H0ZZ00001"]);
  expect(errors).toEqual([]);
});

test("FEC and CONGRESS: no key shows the KEY REQUIRED line, never a table", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/fec?**", (r) =>
    r.fulfill({ status: 424, json: { error: "KEY REQUIRED", kind: "key_required", key: "FEC_API_KEY", detail: "KEY REQUIRED: set FEC_API_KEY in APIKEYS" } }));
  await page.route("**/api/world/congress?**", (r) =>
    r.fulfill({ status: 424, json: { error: "KEY REQUIRED", kind: "key_required", key: "CONGRESS_API_KEY", detail: "KEY REQUIRED: set CONGRESS_API_KEY in APIKEYS" } }));
  await run(page, "FEC smith");
  await expect(panel(page)).toContainText("KEY REQUIRED: set FEC_API_KEY in APIKEYS");
  await expect(panel(page).locator(".sr")).toHaveCount(0);
  await run(page, "CONGRESS");
  // A second command replaces the focused panel (it does not open panel 2), so read the same panel again.
  await expect(panel(page)).toContainText("KEY REQUIRED: set CONGRESS_API_KEY in APIKEYS");
  expect(errors).toEqual([]);
});

test("FEC: no argument shows usage and sends no request", async ({ page }) => {
  const { errors } = await setup(page);
  let calls = 0;
  await page.route("**/api/world/fec?**", (r) => {
    calls++;
    return r.fulfill({ json: env(FEC_SEARCH) });
  });
  await run(page, "FEC");
  await expect(panel(page)).toContainText("USAGE: FEC");
  expect(calls).toBe(0);
  expect(errors).toEqual([]);
});

const BILLS = {
  mode: "LATEST", query: "", fetched: 2, matched: 2, note: "BILLS AS RECORDED BY CONGRESS.GOV. THE LIST HAS NO SPONSOR: ENTER OPENS A BILL FOR ITS SPONSOR AND DETAILS.",
  items: [
    { congress: 119, type: "HR", number: "9001", title: "Example Test Act of 2026", chamber: "House", action_date: "2026-11-03", action: "Referred to the Committee on Example.", updated: "2026-11-04" },
    { congress: 119, type: "S", number: "4242", title: "A bill to study example supply chains", chamber: "Senate", action_date: "2026-11-02", action: "Read twice.", updated: "2026-11-03" },
  ],
};
const BILL = {
  mode: "BILL", congress: 119, type: "HR", number: "9001", title: "Example Test Act of 2026", chamber: "House", introduced: "2026-10-28",
  sponsors: ["Rep. Example, Test A [I-ZZ-1]"], cosponsors: 4, policy_area: "Government Operations", action_date: "2026-11-03", action: "Referred to the Committee on Example.",
  updated: "2026-11-04", note: BILLS.note,
};

test("CONGRESS: latest bills list, Enter opens the highlighted bill with its sponsor, E exports the fields", async ({ page }) => {
  const { errors } = await setup(page);
  const asked: string[] = [];
  await page.route("**/api/world/congress?**", (r) => {
    const q = new URL(r.request().url()).searchParams.get("q") ?? "";
    asked.push(q);
    return r.fulfill({ json: env(q ? BILL : BILLS, { source: "congress.gov (doc-shaped fixture, NOT A RECORDING)" }) });
  });
  await run(page, "CONGRESS");
  const p = panel(page);
  await expect(p).toContainText("LATEST UPDATED");
  await expect(p).toContainText("THE LIST HAS NO SPONSOR");
  await expect(p.locator(".sr")).toContainText("HR 9001");
  await page.keyboard.press("Enter");
  await expect(p).toContainText("HR 9001");
  await expect(p.locator(".sr")).toContainText("BILL");
  const csv = await exportCsv(page);
  expect(csv.name).toContain("CONGRESS_HR9001");
  expect(csv.text).toContain("Rep. Example, Test A [I-ZZ-1]");
  await expect.poll(() => asked).toEqual(["", "119 HR 9001"]);
  expect(errors).toEqual([]);
});

test("CONGRESS: a title filter says it only covers the latest updated bills", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/api/world/congress?**", (r) =>
    r.fulfill({ json: env({ ...BILLS, mode: "TITLE FILTER", query: "zzqx", fetched: 250, matched: 0, items: [], note: "NO FULL-TEXT SEARCH: YOUR WORDS ARE MATCHED AGAINST THE TITLES OF THE 250 MOST RECENTLY UPDATED BILLS ONLY." }) }));
  await run(page, "CONGRESS zzqx");
  await expect(panel(page)).toContainText("0 OF THE 250 MOST RECENTLY UPDATED BILLS MATCH");
  await expect(panel(page)).toContainText("NO FULL-TEXT SEARCH");
  expect(errors).toEqual([]);
});
