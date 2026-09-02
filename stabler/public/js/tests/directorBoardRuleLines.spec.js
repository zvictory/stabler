import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const board = readFileSync(resolve(here, "../pages/tender/DirectorBoard.vue"), "utf8");
const api = readFileSync(resolve(here, "../../../api/tender.py"), "utf8");

/**
 * Acceptance row P8 (prompt 14, director board): every counter's rule line
 * must describe the query that actually produced its number. Measured
 * 2026-09-02 against _tender_director_payload (tender.py:2079-2170): three of
 * the six were false.
 *
 *  - Active tenders claimed `result = null`; visible_count (tender.py:2095) is
 *    incremented for every readable deal BEFORE any result test runs, so it
 *    counts 13 on the seed (S1), not the 10 open ones the rule promised.
 *  - Risk claimed `deadline < 48h`; _milestone (tender.py:1652) sets "risk" on
 *    `days < 0` — already past due, worst of bid/contract/po_eta/delivery —
 *    and never looks at 48 hours anywhere.
 *  - Portfolio value claimed `sum(sales_order.grand_total)`; the value used
 *    (tender.py:2115) is `so_revenue or bid_price` — a Sales Order's total
 *    where one exists, a stored bid price otherwise — and `_deal_revenue`
 *    sums `base_grand_total`, not `grand_total`. 2 of 13 seeded rows come
 *    from an SO, 5 from a bid price: a rule naming only the SO half, and the
 *    wrong field on it, was wrong for the majority of priced rows.
 *
 * The other three rules (`result in (won, lost)`, `avg(margin_on_revenue_pct)`,
 * `value − landed − collected`) were already honest per S1 and stay untouched.
 *
 * Corrected again 2026-09-02 (coordinator review, verified independently):
 * this file's own first-pass fix for Risk, `worst(bid,contract,po_eta,
 * delivery).days < 0`, was itself still not the query — three problems.
 * `worst(...)` returns a status STRING ("good"/"warn"/"risk"), not an object
 * with `.days`. The four-milestone list omits a fifth, conditional one:
 * `_deal_deadlines` (tender.py:1711-1715) appends `guarantee` whenever
 * `intake.guarantee_return` is set, a live user-editable date — a lot whose
 * only overdue date is the guarantee return was counted at_risk while the
 * rule said it could not be. And it had no "not done" term: `_milestone`
 * (tender.py:1650-1653) returns "risk" only when the milestone is NOT done —
 * a done milestone is "good" however far past its date — so by the printed
 * rule a delivered lot with an overdue bid deadline read as at risk while the
 * code said it was not. New string: `any milestone · not done · days < 0`.
 *
 * DOM-less per vitest.config.mjs. Reads both the Vue source (the printed
 * claim) and the Python source (the code behind it) — the same cross-file
 * shape stageColor.spec.js uses reading tender.py from a vitest file — for
 * the same reason: a test that only pinned the string could go green on a
 * rewrite to a DIFFERENT wrong claim.
 */

/** _tender_director_payload's own body, bounded so a match cannot land in a
 *  sibling payload builder that shares vocabulary (visible-count-shaped
 *  loops and has_permission checks exist in more than one function here). */
function payloadBody() {
	const at = api.indexOf("def _tender_director_payload");
	const end = api.indexOf("def _dashboard_executive_payload");
	expect(at, "tender.py: _tender_director_payload has moved").toBeGreaterThan(-1);
	expect(end, "tender.py: _dashboard_executive_payload has moved").toBeGreaterThan(at);
	return api.slice(at, end);
}

/** One counter's own object literal out of the `kpis` array — anchored to
 *  its `key:` and bounded by the entry's own closing `\t\t},` line, not a
 *  fixed character window that could silently slide onto the next counter. */
function kpiEntry(key) {
	const arrAt = board.indexOf("const kpis = computed");
	const arrEnd = board.indexOf("const unverified");
	expect(arrAt, "DirectorBoard.vue: kpis computed has moved").toBeGreaterThan(-1);
	expect(arrEnd, "DirectorBoard.vue: const unverified has moved").toBeGreaterThan(arrAt);
	const kpis = board.slice(arrAt, arrEnd);
	const at = kpis.indexOf(`key: "${key}"`);
	expect(at, `no kpi entry for key "${key}"`).toBeGreaterThan(-1);
	const end = kpis.indexOf("\n\t\t},", at);
	expect(end, `kpi entry for "${key}" has no closing line`).toBeGreaterThan(at);
	return kpis.slice(at, end);
}

describe("P8 — every counter's rule line describes the query that produced it", () => {
	it("Active tenders no longer claims a result filter it does not apply", () => {
		// WHAT WOULD MAKE THIS FAIL: reverting to "tender_lot · result = null".
		// The backend anchor below is what turns this into a fact rather than an
		// opinion: visible_count increments for every readable deal, full stop,
		// with no result branch above the increment.
		const entry = kpiEntry("count");
		expect(entry).not.toMatch(/rule:\s*"tender_lot · result = null"/);
		expect(entry).toMatch(/rule:\s*"tender_lot · every readable deal"/);

		const body = payloadBody();
		const incAt = body.indexOf("visible_count += 1");
		const resultCheckAt = body.indexOf('if _res == "won"');
		expect(incAt, "visible_count += 1 not found").toBeGreaterThan(-1);
		expect(resultCheckAt, "the won/lost/pending branch not found").toBeGreaterThan(incAt);
	});

	it("Risk states the actual predicate: any milestone, not done, days < 0", () => {
		// WHAT WOULD MAKE THIS FAIL: reverting to either string this rule line
		// has already carried and both measured false — "deadline < 48h ·
		// act_now" (S1) and "worst(bid,contract,po_eta,delivery).days < 0"
		// (this row's own first pass). worst(...) is a status STRING, not an
		// object with .days; the four-name list omits `guarantee`, a fifth
		// milestone _deal_deadlines appends whenever intake.guarantee_return is
		// set; and neither string says "not done", so a delivered lot with an
		// overdue bid deadline would read as at risk by the rule while the code
		// (done -> "good", unconditionally) says it is not.
		const entry = kpiEntry("at_risk");
		expect(entry).not.toMatch(/rule:\s*"deadline < 48h · act_now"/);
		expect(entry).not.toMatch(/rule:\s*"worst\(bid,contract,po_eta,delivery\)\.days < 0"/);
		expect(entry).toMatch(/rule:\s*"any milestone · not done · days < 0"/);

		// "any milestone": the rollup walks whatever _deal_deadlines built, and
		// that list is not a fixed four — guarantee is a fifth, conditional
		// entry, appended in the same function the rollup itself lives in.
		const deadlines = api.slice(api.indexOf("def _deal_deadlines"), api.indexOf("def deal_intake"));
		expect(deadlines, "guarantee is no longer a conditional fifth milestone").toMatch(
			/milestones\.append\(\s*_milestone\("guarantee"/
		);
		expect(deadlines, "the risk rollup no longer walks the whole milestones list").toMatch(
			/for m in milestones:\s*if m\["status"\] == "risk":/
		);

		// "not done · days < 0": a true `done` reaches "good" through the `if`
		// and short-circuits before days is ever compared in the `elif`.
		const milestone = api.slice(api.indexOf("def _milestone"), api.indexOf("def _deal_deadlines"));
		expect(milestone).toMatch(/if done:\s*status = "good"\s*elif days < 0:\s*status = "risk"/);
		expect(milestone, "48 (hours) appears in _milestone's own logic").not.toMatch(/48/);
	});

	it("Portfolio value no longer claims an SO-only sum on the wrong field", () => {
		// WHAT WOULD MAKE THIS FAIL: reverting to "sum(sales_order.grand_total)",
		// which named the wrong field AND ignored the fallback: 5 of 13 seeded
		// rows have no Sales Order at all and price from the stored bid instead.
		const entry = kpiEntry("total_value");
		expect(entry).not.toMatch(/rule:\s*"sum\(sales_order\.grand_total\)"/);
		expect(entry).toMatch(/rule:\s*"sum\(sales_order\.base_grand_total or bid_price\)"/);

		const body = payloadBody();
		expect(body).toMatch(/value = flt\(refs\["so_revenue"\]\) or flt\(pnl\["bid_price"\]\)/);
		const revenue = api.slice(api.indexOf("def _deal_revenue("), api.indexOf("def _deal_kassa_actual"));
		expect(revenue, "_deal_revenue no longer sums base_grand_total").toMatch(/base_grand_total/);
	});

	it("the three rules S1 already found honest were not touched", () => {
		// WHAT WOULD MAKE THIS FAIL: editing a rule S1 marked correct. Only three
		// of six were wrong; rewriting a fourth would be a regression this row
		// does not ask for and a claim this test did not measure.
		expect(kpiEntry("win_rate")).toMatch(/rule:\s*"result in \(won, lost\)"/);
		expect(kpiEntry("avg_margin")).toMatch(/rule:\s*"avg\(margin_on_revenue_pct\)"/);
		expect(kpiEntry("ostatok")).toMatch(/rule:\s*"value − landed − collected"/);
	});
});
