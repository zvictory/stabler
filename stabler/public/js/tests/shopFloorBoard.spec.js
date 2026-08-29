// Design 1b — «Канбан: состояние цеха». Which column a Work Order card sits in.
//
// The board was recorded as dead on 2026-08-28 and that call was wrong, for a
// reason worth writing down: it was made against ERPNext's `status` field —
// read-only after submit, 99.1% of rows in one value — while the design's
// columns are a DERIVED shop-floor state and its cards carry buttons, not drag
// handles. The axis that was measured is not the axis the board uses.
//
// What the re-measurement did confirm (anjan, 2026-08-29) is narrower and is the
// reason every rule below is pinned rather than assumed:
//
//     Completed / Closed        3757     Draft                        8
//     nothing transferred yet     33     transferred in full          2
//     partially transferred        0     produced but not finished    0
//     Stabler Line Stop rows       0     completed within the hour  3631 / 3755
//
// Three columns are empty today. They are empty because nobody records those
// steps, not because they cannot be derived — so the state machine covers them
// and the board shows them. A column that does not exist is a step nobody can
// see they are skipping.

import { describe, it, expect } from "vitest";
import { boardColumn, boardGroups, BOARD_COLUMNS } from "../composables/shopFloorBoard.js";

function wo(over = {}) {
	return {
		name: "MFG-WO-0001",
		docstatus: 1,
		status: "Not Started",
		qty: 1000,
		produced_qty: 0,
		transferred_qty: 0,
		required_items: [
			{ item_code: "CREAM", required_qty: 100, transferred_qty: 0, source_warehouse: "Stores - A" },
		],
		...over,
	};
}

describe("the columns are the design's, in the design's order", () => {
	it("names six states, left to right", () => {
		// Pinned as a list because the board renders them in this order and an
		// accidental reshuffle would move every card on the screen without
		// changing a single order.
		expect(BOARD_COLUMNS).toEqual(["draft", "ready", "partial", "running", "paused", "done"]);
	});
});

describe("a card that has not been submitted", () => {
	it("sits in the draft column whatever its status says", () => {
		// ERPNext writes `status: "Draft"` on an unsubmitted order, but the
		// authority is `docstatus` — a status string is derived and a document
		// that has not been submitted cannot be anywhere else.
		expect(boardColumn(wo({ docstatus: 0, status: "Draft" }))).toBe("draft");
		expect(boardColumn(wo({ docstatus: 0, status: "Not Started" }))).toBe("draft");
	});
});

describe("a card that is finished", () => {
	it("sits in the done column", () => {
		for (const status of ["Completed", "Closed"]) {
			expect(boardColumn(wo({ status }))).toBe("done");
		}
	});

	it("stays done even if it produced nothing", () => {
		// A closed order with no output is a decision somebody made, not work in
		// progress. Reading it as running would put a card nobody can act on in
		// the middle of the board.
		expect(boardColumn(wo({ status: "Closed", produced_qty: 0 }))).toBe("done");
	});
});

describe("a card that has been halted", () => {
	it("sits in the paused column", () => {
		// `Stopped` is ERPNext's own halt, and it is the only halted state that
		// exists in the data: `Stabler Line Stop` has no open-stop concept —
		// `to_time` is mandatory, so every logged stop is already over. Deriving
		// "paused" from the stop log would mean calling an order paused because
		// the line stopped for four minutes two hours ago.
		expect(boardColumn(wo({ status: "Stopped" }))).toBe("paused");
	});

	it("is paused even after producing part of the order", () => {
		// The case that decides the precedence: an order halted mid-run has both
		// output and a halt. It belongs where somebody has to act on it.
		expect(boardColumn(wo({ status: "Stopped", produced_qty: 400 }))).toBe("paused");
	});
});

describe("a card that is running", () => {
	it("sits in the running column once anything has come off the line", () => {
		expect(boardColumn(wo({ produced_qty: 1 }))).toBe("running");
	});

	it("sits there on ERPNext's own In Process even before the first unit", () => {
		// The two disagree in the minutes between starting and the first
		// finished unit, and a card that vanishes from the board during those
		// minutes is worse than either.
		expect(boardColumn(wo({ status: "In Process", produced_qty: 0 }))).toBe("running");
	});
});

describe("a card waiting on materials", () => {
	it("is ready when nothing has been issued to it yet", () => {
		expect(boardColumn(wo({ transferred_qty: 0 }))).toBe("ready");
	});

	it("is partial once some — but not all — of the order has been issued", () => {
		// The design's «Частично» column. Measured 0 on anjan today, because
		// material is transferred in one gesture; the column is what makes a
		// half-transferred order visible on the day somebody does it.
		expect(boardColumn(wo({ qty: 1000, transferred_qty: 400 }))).toBe("partial");
	});

	it("is still waiting, not running, when everything has been issued", () => {
		// Fully transferred and nothing produced: the material is at the machine
		// and the machine has not started. Calling that "running" would show two
		// orders on a line that is running one.
		expect(boardColumn(wo({ qty: 1000, transferred_qty: 1000 }))).toBe("partial");
	});

	it("does not read an over-issue as unfinished", () => {
		// ERPNext allows transferring more than the order quantity. `>= qty` and
		// not `=== qty`, or an over-issued order falls out of every branch.
		expect(boardColumn(wo({ qty: 1000, transferred_qty: 1200 }))).toBe("partial");
	});
});

describe("precedence, because a card can match several rules at once", () => {
	it("puts an unsubmitted order in draft even if it looks finished", () => {
		expect(boardColumn(wo({ docstatus: 0, status: "Completed", produced_qty: 1000 }))).toBe("draft");
	});

	it("puts a cancelled order nowhere", () => {
		// A cancelled order is not a state of the shop floor. `null` rather than
		// a seventh column: the board must not grow a bin for work nobody is
		// going to do.
		expect(boardColumn(wo({ docstatus: 2, status: "Cancelled" }))).toBeNull();
	});

	it("prefers done over running for a completed order that produced", () => {
		expect(boardColumn(wo({ status: "Completed", produced_qty: 1000 }))).toBe("done");
	});
});

describe("every card lands somewhere", () => {
	it("gives a submitted order a column no matter what its status string says", () => {
		// ERPNext ships statuses this app never enumerated — anjan carries
		// `Stock Reserved` and `Stock Partially Reserved` today, 1 order each.
		// A card that matches no branch would silently disappear from the board.
		for (const status of ["Stock Reserved", "Stock Partially Reserved", "Хлеб", "", null]) {
			expect(BOARD_COLUMNS).toContain(boardColumn(wo({ status })));
		}
	});
});

describe("the board keeps its shape when a column is empty", () => {
	it("returns every column, including the ones with no cards", () => {
		// Measured on anjan 2026-08-29: `partial`, `running` and `paused` are all
		// 0. A board that drops empty columns would silently become a three-bin
		// board — and the missing bins are exactly the steps nobody records.
		const groups = boardGroups([wo({ status: "Completed" })]);
		expect(Object.keys(groups)).toEqual(BOARD_COLUMNS);
		expect(groups.done.length).toBe(1);
		expect(groups.running).toEqual([]);
		expect(groups.paused).toEqual([]);
	});

	it("drops a cancelled order rather than binning it", () => {
		const groups = boardGroups([wo({ docstatus: 2, status: "Cancelled" })]);
		expect(Object.values(groups).every((g) => g.length === 0)).toBe(true);
	});

	it("survives a null row list", () => {
		expect(Object.keys(boardGroups(null))).toEqual(BOARD_COLUMNS);
	});
});
