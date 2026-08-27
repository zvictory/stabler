import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/inventory/StockReconciliation.vue"), "utf8");

/**
 * A stock reconciliation writes absolute quantities and books the difference to
 * Stock Adjustment — the P&L. The operator who posts it is the last person who
 * can catch a wrong count, so the receipt they are shown has to be the number
 * that moved, not a guess.
 *
 * The page's own `Value delta` (line ~152) is honest as an ESTIMATE: it
 * multiplies the counted difference by the valuation the page loaded when the
 * warehouse was picked. Then the operator walks the warehouse, which takes as
 * long as counting a warehouse takes, and any receipt landing in that window
 * moves the real valuation. The estimate and the posting then disagree, and the
 * posting is the one that hits the ledger.
 *
 * `create_stock_reconciliation` reads the posted document's own
 * `difference_amount` back (see the D-INV-2 note in api/inventory.py, measured
 * on genesis-test: the estimate said 0.5 while the GL moved 729.5). This spec
 * pins that the confirmation shows THAT number and not the page's estimate —
 * otherwise the honest figure is computed on the server and thrown away.
 *
 * vitest runs on node here with no jsdom and no @vue/test-utils, so
 * `postReconciliation` is extracted from the SFC and executed against stubs,
 * the same approach as operatorWriteOffGate.spec.js.
 */
function postReconciliationSource() {
	const start = src.indexOf("async function postReconciliation()");
	expect(start, "no postReconciliation in the SFC").toBeGreaterThan(-1);
	const end = src.indexOf("\n}", start);
	expect(end, "unterminated postReconciliation").toBeGreaterThan(start);
	return src.slice(start, end + 2);
}

const DEPS = [
	"changed",
	"toast",
	"t",
	"confirm",
	"busy",
	"warehouse",
	"call",
	"activeCompany",
	"todayIso",
	"loadBalances",
	"loadRecents",
	"money",
	"totalValueDelta",
];

/** Post one changed line; `serverResponse` is what the endpoint returns. */
async function post({ serverResponse, pageEstimate }) {
	const success = [];
	const errors = [];
	const sent = [];
	const stubs = {
		changed: { value: [{ item_code: "PROBE-MILK", actual_qty: 730, counted: 731, valuation_rate: 1 }] },
		toast: { success: (m) => success.push(m), error: (m) => errors.push(m) },
		t: (s) => s, // no catalog in node; the key is the English source string
		confirm: async () => true,
		busy: { value: false },
		warehouse: { value: "Stores - _TC" },
		call: async (method, args) => {
			sent.push({ method, args });
			return serverResponse;
		},
		activeCompany: { value: "Probe Co" },
		todayIso: () => "2026-08-27",
		loadBalances: async () => {},
		loadRecents: async () => {},
		money: (v) => `UZS ${Number(v || 0).toFixed(2)}`,
		totalValueDelta: { value: pageEstimate },
	};
	const build = new Function(...DEPS, `${postReconciliationSource()}\nreturn postReconciliation;`);
	await build(...DEPS.map((d) => stubs[d]))();
	return { success, errors, sent };
}

describe("what the operator is told after a count is posted", () => {
	it("reports the value the ledger actually moved, not the page's estimate", async () => {
		const { success, errors } = await post({
			serverResponse: { changed_lines: 1, summary: { total_value_delta: 729.5, total_qty_delta: 1 } },
			pageEstimate: 4242.42,
		});
		expect(errors, "posting succeeded, so nothing should be reported as an error").toEqual([]);
		expect(success).toHaveLength(1);
		expect(success[0], "the posted difference is missing from the receipt").toContain("729.50");
		expect(success[0], "the stale page estimate must not be presented as what was posted").not.toContain(
			"4242.42",
		);
	});

	it("still says how many lines were reconciled", async () => {
		const { success } = await post({
			serverResponse: { changed_lines: 3, summary: { total_value_delta: -12, total_qty_delta: -4 } },
			pageEstimate: 0,
		});
		expect(success[0]).toContain("3");
	});

	it("does not break the confirmation when the server sends no summary", async () => {
		// An older worker mid-deploy, or any future shape change: the count was
		// still posted, so the operator must get a confirmation rather than a
		// TypeError swallowed into the error toast.
		const { success, errors } = await post({
			serverResponse: { changed_lines: 2 },
			pageEstimate: 5,
		});
		expect(errors).toEqual([]);
		expect(success).toHaveLength(1);
		expect(success[0]).toContain("2");
	});
});
