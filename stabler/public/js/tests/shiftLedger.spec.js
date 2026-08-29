// The header strip of the Work Order register — the half of design 1a that was
// never built. The table shipped; the ledger above it did not, and without it
// the screen answers "what are the orders" but not "how is the shift going".
//
// Every number here is derived from the rows the table is already showing, and
// that is the point rather than an economy: a header computed from a second,
// wider query can disagree with the list under it, and a supervisor who sees
// "2 orders short" above a list with three orange chips trusts neither. Agreeing
// by construction is worth more than covering rows the table is not displaying.
//
// One shift, measured 2026-08-29: `Смена A/B/C` in the design has no backing
// field on Work Order, and the factory runs a single shift, so nothing here
// splits by shift and no tile claims one.

import { describe, it, expect } from "vitest";
import { shiftSummary, ledgerView } from "../composables/shiftLedger.js";
import { stockKey } from "../composables/materialReadiness.js";

/** A row shaped like `list_work_orders` returns it. */
function wo(over = {}) {
	return {
		name: "MFG-WO-0001",
		qty: 1000,
		produced_qty: 0,
		status: "Not Started",
		planned_end_date: "2026-08-29 14:00:00",
		required_items: [
			{
				item_code: "CREAM",
				required_qty: 100,
				transferred_qty: 0,
				source_warehouse: "Stores - A",
			},
		],
		...over,
	};
}

const NOW = new Date("2026-08-29T12:00:00");
const PLENTY = { [stockKey("Stores - A", "CREAM")]: 10000 };
const NOTHING = { [stockKey("Stores - A", "CREAM")]: 0 };

describe("what the shift planned and what came off the line", () => {
	it("adds the planned and produced quantities of the rows on screen", () => {
		const s = shiftSummary([wo({ qty: 4000, produced_qty: 2640 }), wo({ qty: 1200 })], PLENTY, NOW);
		expect(s.planQty).toBe(5200);
		expect(s.producedQty).toBe(2640);
		expect(s.orders).toBe(2);
	});

	it("leaves a cancelled order out of the plan but still counts it as a row", () => {
		// A cancelled order is not work anybody is going to do, so counting its
		// quantity would inflate the shift's plan and make the completion figure
		// read low for the rest of the day. It stays in `orders` because the
		// table is still showing it — the strip describes the list, not a
		// different set the user cannot see.
		const s = shiftSummary([wo({ qty: 4000 }), wo({ qty: 9000, status: "Cancelled" })], PLENTY, NOW);
		expect(s.planQty).toBe(4000);
		expect(s.orders).toBe(2);
	});

	it("reads produced against plan as a percentage, and refuses to divide by nothing", () => {
		expect(shiftSummary([wo({ qty: 1000, produced_qty: 250 })], PLENTY, NOW).donePct).toBe(25);
		// Every row cancelled: the plan is zero and there is no percentage to
		// state. `0` would read as "nothing done" and `Infinity` renders as junk.
		expect(shiftSummary([wo({ status: "Cancelled" })], PLENTY, NOW).donePct).toBeNull();
	});

	it("counts overproduction honestly rather than capping it at the plan", () => {
		// ERPNext allows finishing more than was planned, and a shift that ran
		// 10% over is exactly what a supervisor wants to see. Clamping to 100%
		// would hide it.
		expect(shiftSummary([wo({ qty: 1000, produced_qty: 1100 })], PLENTY, NOW).donePct).toBe(110);
	});
});

describe("which orders can go on a machine right now", () => {
	it("counts an order whose shelf covers it", () => {
		expect(shiftSummary([wo()], PLENTY, NOW).ready).toBe(1);
	});

	it("counts an order whose materials are already in WIP", () => {
		// Nothing outstanding to issue: this is the readiest an order gets, and
		// an earlier version of this strip missed it because `in_place` is a
		// different state from `ready`.
		const row = wo({ required_items: [{ item_code: "CREAM", required_qty: 100, transferred_qty: 100, source_warehouse: "Stores - A" }] });
		expect(shiftSummary([row], NOTHING, NOW).ready).toBe(1);
	});

	it("does not call an order that is already running ready to start", () => {
		// "Готовы к запуску" is a queue to act on. An order in process is not in
		// that queue, and putting it there sends a supervisor to a machine that
		// is already busy.
		expect(shiftSummary([wo({ status: "In Process", produced_qty: 500 })], PLENTY, NOW).ready).toBe(0);
	});

	it("does not call a draft ready to start", () => {
		// A draft cannot be put on a machine — it has to be submitted first. The
		// design shows `Черновик` as its own status for exactly that reason, so
		// counting one here sends a supervisor to an order nothing can run.
		expect(shiftSummary([wo({ status: "Draft" })], PLENTY, NOW).ready).toBe(0);
	});

	it("does not call a finished or cancelled order ready", () => {
		for (const status of ["Completed", "Closed", "Stopped", "Cancelled"]) {
			expect(shiftSummary([wo({ status })], PLENTY, NOW).ready).toBe(0);
		}
	});

	it("does not call an order ready when the shelf cannot cover it", () => {
		expect(shiftSummary([wo()], NOTHING, NOW).ready).toBe(0);
	});

	it("does not guess when a shelf was never measured", () => {
		// `materialReadiness` returns `unknown` rather than inventing a balance.
		// Counting an unknown as ready would send somebody to an empty store;
		// counting it as short would raise an alarm about nothing. It is neither.
		const s = shiftSummary([wo()], {}, NOW);
		expect(s.ready).toBe(0);
		expect(s.shortOrders).toBe(0);
		expect(s.unknown).toBe(1);
	});
});

describe("what the store cannot cover", () => {
	it("counts the orders that are short and the lines under them", () => {
		const row = wo({
			required_items: [
				{ item_code: "CREAM", required_qty: 100, transferred_qty: 0, source_warehouse: "Stores - A" },
				{ item_code: "BOX", required_qty: 40, transferred_qty: 0, source_warehouse: "Stores - A" },
			],
		});
		const stock = { [stockKey("Stores - A", "CREAM")]: 0, [stockKey("Stores - A", "BOX")]: 0 };
		const s = shiftSummary([row], stock, NOW);
		expect(s.shortOrders).toBe(1);
		expect(s.shortItems).toBe(2);
	});

	it("does not report a shortage against an order nobody is going to run", () => {
		// A cancelled order still carries material lines, and a store that
		// cannot cover them is not a problem anybody has to solve.
		expect(shiftSummary([wo({ status: "Cancelled" })], NOTHING, NOW).shortOrders).toBe(0);
	});
});

describe("what has run out of time", () => {
	it("counts an open order whose window has already closed", () => {
		expect(shiftSummary([wo({ planned_end_date: "2026-08-29 09:00:00" })], PLENTY, NOW).overdue).toBe(1);
	});

	it("does not count an order that finished late", () => {
		// It ended after its window, but it ended. Listing it as overdue puts
		// history in a queue meant for things that still need a decision.
		const row = wo({ planned_end_date: "2026-08-29 09:00:00", status: "Completed" });
		expect(shiftSummary([row], PLENTY, NOW).overdue).toBe(0);
	});

	it("does not count an order whose window has not closed yet", () => {
		expect(shiftSummary([wo({ planned_end_date: "2026-08-29 18:00:00" })], PLENTY, NOW).overdue).toBe(0);
	});

	it("treats a missing end date as not overdue", () => {
		// A draft with no window is incomplete, not late. Reading a null date as
		// "1970" would put every unplanned draft in the overdue queue.
		for (const planned_end_date of [null, "", undefined]) {
			expect(shiftSummary([wo({ planned_end_date })], PLENTY, NOW).overdue).toBe(0);
		}
	});
});

describe("the tabs filter the same rows the strip counted", () => {
	const rows = [
		wo({ name: "A" }), // ready
		wo({ name: "B", status: "In Process", produced_qty: 10 }),
		wo({ name: "C", planned_end_date: "2026-08-29 09:00:00" }), // overdue AND ready
	];

	it("shows everything under the first tab", () => {
		expect(ledgerView(rows, "all", PLENTY, NOW).map((r) => r.name)).toEqual(["A", "B", "C"]);
	});

	it("agrees with the strip's ready count", () => {
		const view = ledgerView(rows, "ready", PLENTY, NOW);
		expect(view.map((r) => r.name)).toEqual(["A", "C"]);
		expect(view.length).toBe(shiftSummary(rows, PLENTY, NOW).ready);
	});

	it("agrees with the strip's overdue count", () => {
		const view = ledgerView(rows, "overdue", PLENTY, NOW);
		expect(view.map((r) => r.name)).toEqual(["C"]);
		expect(view.length).toBe(shiftSummary(rows, PLENTY, NOW).overdue);
	});

	it("falls back to everything on a tab it does not know", () => {
		// The tab name arrives from a route or a stale bookmark. Showing an empty
		// table would read as "no work today" on a shift that has plenty.
		expect(ledgerView(rows, "хлеб", PLENTY, NOW).length).toBe(3);
	});
});

describe("an empty register says nothing rather than zero", () => {
	it("returns a summary with no percentage and no counts", () => {
		const s = shiftSummary([], PLENTY, NOW);
		expect(s.orders).toBe(0);
		expect(s.planQty).toBe(0);
		expect(s.donePct).toBeNull();
	});

	it("survives a null row list", () => {
		expect(shiftSummary(null, PLENTY, NOW).orders).toBe(0);
	});
});
