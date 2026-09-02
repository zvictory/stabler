import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const board = readFileSync(resolve(here, "../pages/tender/DirectorBoard.vue"), "utf8");
const api = readFileSync(resolve(here, "../../../api/tender.py"), "utf8");
const TEMPLATE = board.slice(board.indexOf("<template>"), board.indexOf("<style scoped>"));

/**
 * Acceptance row P9 (prompt 14, director board): "not yet priced" must be
 * distinguishable from an honest zero.
 *
 * Measured 2026-09-02 (prompt doc S2): custom_bid_pricing is written only for
 * stages priced/submitted/won/lost (seed_tender_demo.py:663). Six of the
 * seed's thirteen deals — still at `seen` — have no pricing plan, and
 * _tender_director_payload had no field saying so: `value = so_revenue or
 * bid_price` (tender.py:2115) is 0 for both "nothing priced yet" and "priced
 * at exactly zero", and the template rendered both as "0" in Value, Margin,
 * Landed and Остаток, under a header that reads "Portfolio value". Same
 * defect class as prompt 12's Transport column — a measurement that was
 * never taken, printed as though it had been.
 *
 * The fix adds one field to the row payload — `priced` — computed with the
 * IDENTICAL has_pricing_col / has_pricing idiom tender.py already runs three
 * other places (funnel classify, desk queue, my-tenders queue), so this is
 * not a new way of knowing the fact, and reads it on the client instead of
 * inferring "priced" from whether a number happens to be nonzero.
 *
 * DOM-less, cross-file like stageColor.spec.js (reads tender.py from vitest).
 */

function payloadBody() {
	const at = api.indexOf("def _tender_director_payload");
	const end = api.indexOf("def _dashboard_executive_payload");
	expect(at, "tender.py: _tender_director_payload has moved").toBeGreaterThan(-1);
	expect(end, "tender.py: _dashboard_executive_payload has moved").toBeGreaterThan(at);
	return api.slice(at, end);
}

describe("P9 — the server states whether a row has a pricing plan", () => {
	it("computes has_pricing with the same idiom the rest of tender.py already uses", () => {
		// WHAT WOULD MAKE THIS FAIL: inventing a second way to read
		// custom_bid_pricing, or reading it once for the whole company instead
		// of per deal. Three other payload builders in this file already run
		// `has_pricing_col and frappe.db.get_value("CRM Deal", deal,
		// "custom_bid_pricing")` per row; a differently-spelled fourth copy is a
		// second source of truth for the identical fact.
		const body = payloadBody();
		expect(body).toMatch(/has_pricing_col = frappe\.db\.has_column\("CRM Deal", "custom_bid_pricing"\)/);
		expect(body).toMatch(
			/has_pricing = bool\(has_pricing_col and frappe\.db\.get_value\("CRM Deal", deal, "custom_bid_pricing"\)\)/
		);
	});

	it("puts it on the row the client reads", () => {
		// WHAT WOULD MAKE THIS FAIL: computing has_pricing and never adding it to
		// the row dict — landed, wired to nothing, the exact shape
		// stageColor.spec.js's own precedent warns about.
		const body = payloadBody();
		const rowAt = body.indexOf('"deal": deal,');
		const rowEnd = body.indexOf("kpi = {");
		expect(rowAt, "row dict not found").toBeGreaterThan(-1);
		expect(rowEnd, "kpi dict not found after the row").toBeGreaterThan(rowAt);
		const rowDict = body.slice(rowAt, rowEnd);
		expect(rowDict).toMatch(/"priced":\s*has_pricing,/);
	});
});

describe("P9 follow-up (coordinator review, 2026-09-02) — the header must agree with the row", () => {
	it("total_value, total_ost and margins are accumulated only for priced deals", () => {
		// WHAT WOULD MAKE THIS FAIL: today's unconditional accumulation. _bid_inputs
		// / _compute_bid_pnl run for every deal regardless of has_pricing and fall
		// back to _BID_DEFAULTS (mode: margin, margin_pct: 20.0) when nothing is
		// stored — landed_goods of 1,000,000 back-solves to bid_price 1402946.19,
		// margin_on_revenue_pct 20.0, ostatok 202299.83, all computed from nothing
		// a human entered. Before this fix that invented figure landed in Portfolio
		// value, Остаток and Avg margin for a deal whose OWN row prints "—" — a
		// director cannot reconcile a KPI with the column that composes it. Gating
		// on has_pricing is also what makes avg_margin's note ("average across
		// tenders that have pricing", unchanged by this fix) true rather than
		// aspirational: margins.append was previously gated on the margin being
		// non-zero, and the default gives exactly a non-zero 20.0.
		const body = payloadBody();
		const gated =
			"\t\tif has_pricing:\n" +
			"\t\t\ttotal_value += value\n" +
			"\t\t\ttotal_ost += flt(pnl[\"ostatok\"])\n" +
			"\t\t\tif pnl[\"margin_on_revenue_pct\"]:\n" +
			"\t\t\t\tmargins.append(pnl[\"margin_on_revenue_pct\"])";
		expect(body, "total_value/total_ost/margins are not gated on has_pricing").toContain(gated);
	});
});

describe("P9 — a row with no pricing plan does not print a zero", () => {
	it("the Value/Margin/Landed/Остаток cells render a placeholder instead of fm(0)/0%", () => {
		// WHAT WOULD MAKE THIS FAIL: calling fm(r.value) unconditionally, which
		// is what rendered "0" for six of the thirteen seeded rows under a
		// header that reads "Portfolio value".
		expect(TEMPLATE).toMatch(/\{\{\s*r\.priced \? fm\(r\.value\) : "—"\s*\}\}/);
		expect(TEMPLATE).toMatch(/\{\{\s*r\.priced \? `\$\{r\.margin_pct\}%` : "—"\s*\}\}/);
		expect(TEMPLATE).toMatch(/\{\{\s*r\.priced \? fm\(r\.landed\) : "—"\s*\}\}/);
		expect(TEMPLATE).toMatch(/\{\{\s*r\.priced \? fm\(r\.ostatok\) : "—"\s*\}\}/);
	});

	it("the Tender cell names the state instead of leaving four dashes to speak for themselves", () => {
		// WHAT WOULD MAKE THIS FAIL: the dash cells landing with no chip. Four
		// dashes still read as "missing data" or a loading glitch without
		// something that says, in words, that this lot has not been priced yet —
		// a mutation that deletes just the chip branch while keeping the dashes
		// is the case this test exists to catch on its own, independent of the
		// previous one.
		const tenderCellAt = TEMPLATE.indexOf('class="board-tender"');
		const tenderCellEnd = TEMPLATE.indexOf('class="ds-row-ev"', tenderCellAt);
		expect(tenderCellAt, "board-tender cell not found").toBeGreaterThan(-1);
		expect(tenderCellEnd, "ds-row-ev not found after board-tender").toBeGreaterThan(tenderCellAt);
		const cell = TEMPLATE.slice(tenderCellAt, tenderCellEnd);
		expect(cell).toMatch(/v-else-if="!r\.priced"/);
		expect(cell).toMatch(/t\("Not yet priced"\)/);
	});

	it("the not-yet-priced chip does not fire on a row that already has a result", () => {
		// WHAT WOULD MAKE THIS FAIL: an unconditional v-if instead of the
		// existing if/else-if chain — a won or lost deal would then show BOTH
		// its result chip and "Not yet priced" at once, which is nonsense: a
		// deal that has already won or lost has, by construction, been priced.
		const tenderCellAt = TEMPLATE.indexOf('class="board-tender"');
		const tenderCellEnd = TEMPLATE.indexOf('class="ds-row-ev"', tenderCellAt);
		const cell = TEMPLATE.slice(tenderCellAt, tenderCellEnd);
		const resultAt = cell.indexOf('v-if="r.result"');
		const unverifiedAt = cell.indexOf('v-else-if="r.lifecycle?.unverified_history"');
		const pricedAt = cell.indexOf('v-else-if="!r.priced"');
		expect(resultAt).toBeGreaterThan(-1);
		expect(unverifiedAt).toBeGreaterThan(resultAt);
		expect(pricedAt).toBeGreaterThan(unverifiedAt);
	});
});
