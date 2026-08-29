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
import {
	boardColumn,
	boardGroups,
	transferredPct,
	cardAction,
	doneEarlier,
	BOARD_COLUMNS,
} from "../composables/shopFloorBoard.js";

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
	it("names five states, left to right", () => {
		// Pinned as a list because the board renders them in this order and an
		// accidental reshuffle would move every card on the screen without
		// changing a single order.
		expect(BOARD_COLUMNS).toEqual(["draft", "ready", "running", "paused", "done"]);
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

	it("is still ready once material has been issued but nothing has run", () => {
		// There is no «Частично» column, and the design is the reason: it draws a
		// half-issued order as a card in «Готов к запуску» carrying a «Частично»
		// BUTTON, and writes the share as a line on the card («передано 50%»).
		// A column of its own was mine, not the design's, and it held 0 rows on
		// anjan — a permanently empty bin that pushed the five real ones off a
		// laptop screen.
		expect(boardColumn(wo({ qty: 1000, transferred_qty: 400 }))).toBe("ready");
	});

	it("is still ready, not running, when everything has been issued", () => {
		// Fully transferred and nothing produced: the material is at the machine
		// and the machine has not started. Calling that "running" would show two
		// orders on a line that is running one.
		expect(boardColumn(wo({ qty: 1000, transferred_qty: 1000 }))).toBe("ready");
	});
});

describe("how much of an order has been issued", () => {
	it("is the share of the ordered quantity", () => {
		expect(transferredPct(wo({ qty: 1000, transferred_qty: 500 }))).toBe(50);
	});

	it("rounds to a whole percent, because the card has one line for it", () => {
		expect(transferredPct(wo({ qty: 3000, transferred_qty: 901 }))).toBe(30);
	});

	it("is null when nothing has been issued", () => {
		// Not 0: the card renders this line only when there is something to say,
		// and «передано 0%» on every waiting order is furniture.
		expect(transferredPct(wo({ qty: 1000, transferred_qty: 0 }))).toBeNull();
	});

	it("is null when the order has no quantity", () => {
		// A share of nothing is not 0%, it is unanswerable — and dividing by it
		// would put `Infinity%` on the card.
		expect(transferredPct(wo({ qty: 0, transferred_qty: 5 }))).toBeNull();
	});

	it("does not report more than the whole order", () => {
		// ERPNext allows an over-issue. «передано 120%» reads as a bug in the
		// card rather than as a fact about the store.
		expect(transferredPct(wo({ qty: 1000, transferred_qty: 1200 }))).toBe(100);
	});
});

describe("the one action a card offers", () => {
	it("releases a draft", () => {
		expect(cardAction(wo({ docstatus: 0 }))).toEqual({ kind: "submit", label: "Submit" });
	});

	it("issues and starts an order that is waiting", () => {
		expect(cardAction(wo({ transferred_qty: 0 }))).toEqual({
			kind: "transfer",
			label: "Transfer and start",
		});
	});

	it("finishes an order that is running", () => {
		expect(cardAction(wo({ status: "In Process" }))).toEqual({ kind: "produce", label: "Finish" });
	});

	it("resumes an order that is halted", () => {
		expect(cardAction(wo({ status: "Stopped" }))).toEqual({ kind: "resume", label: "Resume" });
	});

	it("closes an order that finished producing", () => {
		expect(cardAction(wo({ status: "Completed" }))).toEqual({
			kind: "close",
			label: "Close order",
		});
	});

	it("offers nothing on an order that is already closed", () => {
		// `done` holds both, and a Close button on a closed order is a button
		// whose only outcome is an error message from the server.
		expect(cardAction(wo({ status: "Closed" }))).toBeNull();
	});

	it("offers nothing on a cancelled order", () => {
		expect(cardAction(wo({ docstatus: 2, status: "Cancelled" }))).toBeNull();
	});

	it("names an action for every column the board renders", () => {
		// Except `done`, which is the one column whose cards can legitimately
		// have nothing left to do. A column with no action at all would be a
		// board somebody has to leave to get anything done.
		const byColumn = {
			draft: wo({ docstatus: 0 }),
			ready: wo({}),
			running: wo({ status: "In Process" }),
			paused: wo({ status: "Stopped" }),
			done: wo({ status: "Completed" }),
		};
		for (const key of BOARD_COLUMNS) {
			expect(cardAction(byColumn[key])).not.toBeNull();
		}
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

describe("the finished column holds the shift, not the year", () => {
	// «Завершён · смена» in the design, and the reason is arithmetic: anjan holds
	// 3 756 finished orders against 2 finished today (measured 2026-08-29). An
	// unbounded column is a 3 756-card scroll that buries the five cards anybody
	// on the floor is working with, and it makes the column's quantity total a
	// number about the year rather than about the shift.
	//
	// One calendar day, because one shift runs. A site running the design's three
	// shifts (С · 22:00–06:00 crosses midnight) would need a window with an hour
	// on both ends, and that is not this factory.
	const day = "2026-08-29";
	const finished = (name, at) =>
		wo({ name, status: "Completed", produced_qty: 1000, actual_end_date: at });

	it("keeps an order finished during the day", () => {
		const groups = boardGroups([finished("A", "2026-08-29 06:12:00")], day);
		expect(groups.done.map((r) => r.name)).toEqual(["A"]);
	});

	it("drops one finished on an earlier day", () => {
		const groups = boardGroups([finished("B", "2026-08-28 23:59:00")], day);
		expect(groups.done).toEqual([]);
	});

	it("drops one that never recorded finishing", () => {
		// A Work Order closed by hand never ran, so it has no `actual_end_date`.
		// It is finished, but it is not this shift's output — and counting it
		// would put a card with no quantity into the shift's quantity total.
		const groups = boardGroups([finished("C", null)], day);
		expect(groups.done).toEqual([]);
	});

	it("leaves every other column alone", () => {
		// The window is about output, not about when an order was created. A draft
		// entered last month is still a draft that has to be released today.
		const groups = boardGroups([wo({ name: "D", docstatus: 0 })], day);
		expect(groups.draft.map((r) => r.name)).toEqual(["D"]);
	});

	it("shows the whole history when no shift is given", () => {
		// The list view has date filters of its own and no such promise in its
		// header. Passing nothing must not silently hide rows.
		const groups = boardGroups([finished("E", "2019-01-01 08:00:00")]);
		expect(groups.done.map((r) => r.name)).toEqual(["E"]);
	});

	it("counts what the window hid rather than losing it", () => {
		// The cards are hidden, the fact is not: a column header reading "2" over
		// a factory that finished 3 756 orders is true and misleading, and the
		// difference is what tells a supervisor the filter is on.
		const rows = [
			finished("A", "2026-08-29 06:12:00"),
			finished("B", "2026-08-28 10:00:00"),
			finished("C", null),
			wo({ name: "D", docstatus: 0 }),
		];
		expect(doneEarlier(rows, day)).toBe(2);
		expect(doneEarlier(rows)).toBe(0);
	});
});

describe("the board keeps its shape when a column is empty", () => {
	it("returns every column, including the ones with no cards", () => {
		// Measured on anjan 2026-08-29: `running` and `paused` are both 0. A board
		// that drops empty columns would silently lose them — and they are exactly
		// the steps nobody records.
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
