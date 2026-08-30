/**
 * Real-browser walkthrough of the WHAT IF exploration flow.
 * Drives the actual UI at localhost:3000 against the live Docker stack.
 */
import { chromium } from "@playwright/test";
import { writeFileSync } from "node:fs";

const SHOTS = process.env.SHOT_DIR;
const SCENARIO = `I have been running a two-person design studio for three years. A larger agency offered to acquire us and keep both of us on salary for two years. Our current clients are stable but we have no savings buffer beyond four months.`;

const log = (...a) => console.log(...a);
const netCalls = [];
const consoleErrors = [];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

page.on("console", (m) => {
  if (m.type() === "error") consoleErrors.push(m.text());
});
page.on("pageerror", (e) => consoleErrors.push(`PAGEERROR: ${e.message}`));
page.on("response", async (r) => {
  const u = r.url();
  if (u.includes("/api/v1/")) {
    netCalls.push({ status: r.status(), url: u.replace(/^https?:\/\/[^/]+/, ""), method: r.request().method() });
  }
});

async function shot(name) {
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });
  log(`  [shot] ${name}.png`);
}

// ---- 1. landing page ----
log("\n=== 1. LANDING ===");
await page.goto("http://localhost:3000/", { waitUntil: "networkidle" });
log("  title:", await page.title());
const status = await page.getByTestId("api-status").textContent().catch(() => "(none)");
log("  header status pill:", status.trim());
await shot("01-landing");

// ---- 2. submit a scenario ----
log("\n=== 2. SUBMIT SCENARIO ===");
const box = page.locator("textarea").first();
await box.fill(SCENARIO);
log("  typed", SCENARIO.length, "chars");
await shot("02-typed");

await page.getByRole("button", { name: /explore|map|start|submit/i }).first().click();
await page.waitForURL(/\/scenario\//, { timeout: 60_000 });
const scenarioId = page.url().split("/scenario/")[1];
log("  navigated to scenario:", scenarioId);

// ---- 3. extraction ----
log("\n=== 3. EXTRACTION (live model) ===");
const t0 = Date.now();
await page.getByTestId("reality-review").waitFor({ timeout: 600_000 });
log(`  reality review rendered in ${((Date.now() - t0) / 1000).toFixed(1)}s`);
const domain = await page.getByTestId("domain-badge").textContent();
log("  domain routed to:", domain.trim());
const mockBanner = await page.getByTestId("mock-banner").count();
log("  mock banner shown:", mockBanner > 0, "(expect false on live model)");
await shot("03-reality");

// ---- 4. generation with SSE progress ----
log("\n=== 4. GENERATE (watching SSE stage events) ===");
const seenStages = [];
const poll = setInterval(async () => {
  const el = await page.getByTestId("stage-progress").count();
  if (el) {
    const txt = await page.getByTestId("stage-progress").innerText().catch(() => "");
    const first = txt.split("\n").filter(Boolean)[0];
    if (first && seenStages.at(-1) !== first) {
      seenStages.push(first);
      log("  stage:", first);
    }
  }
}, 700);

const g0 = Date.now();
await page.getByTestId("generate-button").click();
await page.getByTestId("possibility-graph").waitFor({ timeout: 900_000 });
clearInterval(poll);
log(`  graph rendered in ${((Date.now() - g0) / 1000).toFixed(1)}s`);
log("  distinct stage labels seen in UI:", seenStages.length);

const depthLine = await page.getByTestId("graph-depth").textContent();
log("  graph summary:", depthLine.trim());
await shot("04-graph");

// ---- 5. open detail on an outcome node ----
log("\n=== 5. BRANCH DETAIL SHEET ===");
const stateNodes = page.locator(".react-flow__node-state");
const nodeCount = await stateNodes.count();
log("  outcome nodes on canvas:", nodeCount);
await stateNodes.first().click();
await page.getByTestId("branch-detail").waitFor({ timeout: 15_000 });
const sheet = page.getByTestId("branch-detail");
log("  sheet title:", (await sheet.locator("h3").first().textContent()).trim());
log("  has score breakdown:", (await page.getByTestId("score-breakdown").count()) > 0);
log("  has state delta:", (await page.getByTestId("state-delta").count()) > 0);
await shot("05-detail-sheet");
await page.getByLabel("Close details").click();

// ---- 6. click a FORK node (used to show nothing) ----
log("\n=== 6. FORK NODE DETAIL (regression: used to render nothing) ===");
const forks = page.locator(".react-flow__node-decision");
log("  fork nodes on canvas:", await forks.count());
await forks.first().click();
const forkSheetVisible = await page.getByTestId("branch-detail").isVisible().catch(() => false);
log("  fork sheet renders:", forkSheetVisible);
if (forkSheetVisible) {
  const txt = await page.getByTestId("branch-detail").innerText();
  log("  fork sheet first line:", txt.split("\n").filter(Boolean)[0]);
  await shot("06-fork-detail");
  await page.getByLabel("Close details").click();
}

// ---- 7. expand a branch ----
log("\n=== 7. FORK AGAIN (expand-on-click, live model) ===");
const expandBtn = page.locator('[data-testid^="expand-"]').first();
const hasExpand = (await expandBtn.count()) > 0;
log("  expand affordance present:", hasExpand);
let expanded = false;
if (hasExpand) {
  const before = await stateNodes.count();
  const e0 = Date.now();
  await expandBtn.click();
  await shot("07-expanding");
  try {
    await page.waitForFunction(
      (n) => document.querySelectorAll(".react-flow__node-state").length > n,
      before,
      { timeout: 900_000 }
    );
    expanded = true;
    log(`  expanded in ${((Date.now() - e0) / 1000).toFixed(1)}s: ${before} -> ${await stateNodes.count()} outcome nodes`);
    log("  graph summary now:", (await page.getByTestId("graph-depth").textContent()).trim());
    await shot("08-expanded");
  } catch {
    log("  !! expansion did not complete in time");
    await shot("08-expand-timeout");
  }
}

// ---- 8. compare via shift-click ----
log("\n=== 8. COMPARE MODE (shift-click) ===");
await stateNodes.nth(0).click();
await stateNodes.nth(1).click({ modifiers: ["Shift"] });
const cmp = await page.getByTestId("compare-panel").count();
log("  compare panel rendered:", cmp > 0);
if (cmp > 0) {
  const rows = await page.getByTestId("compare-panel").locator("tbody tr").count();
  log("  dimension rows:", rows);
  log("  note:", (await page.getByTestId("compare-note").textContent()).trim());
  await shot("09-compare");
}

// ---- results ----
log("\n=== NETWORK CALLS (frontend -> API) ===");
const byRoute = {};
for (const c of netCalls) {
  const key = `${c.method} ${c.url.replace(/[0-9a-f-]{36}/g, "{id}")}`;
  byRoute[key] = (byRoute[key] || 0) + 1;
}
for (const [k, v] of Object.entries(byRoute).sort((a, b) => b[1] - a[1])) log(`  ${v}x  ${k}`);
const bad = netCalls.filter((c) => c.status >= 400);
log("  non-2xx responses:", bad.length, bad.length ? JSON.stringify(bad.slice(0, 5)) : "");

log("\n=== CONSOLE ERRORS ===");
log(consoleErrors.length ? consoleErrors.slice(0, 10).join("\n") : "  none");

writeFileSync(`${SHOTS}/summary.json`, JSON.stringify({ scenarioId, expanded, netCalls, consoleErrors }, null, 2));
await browser.close();
log("\nscenario id:", scenarioId);
