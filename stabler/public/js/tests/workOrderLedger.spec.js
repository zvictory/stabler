// The shift ledger's wiring into the register page.
//
// The arithmetic is pinned by `shiftLedger.spec.js`, which executes it. What is
// left here is the wiring, and wiring is where this feature can silently stop
// working while every logic test stays green: a strip that counts `rows` while
// the table renders `visibleRows` shows a badge of 9 above a list of 2, and no
// unit test of either half would notice.
//
// Read out of the shipped `.vue` rather than mounted — `@vue/test-utils` is not
// a dependency of this repo, and the house pattern is to extract from source and
// execute what can be executed.

import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { BOARD_COLUMNS } from "../composables/shopFloorBoard.js";
import { fileURLToPath } from "url";

const src = readFileSync(
	fileURLToPath(new URL("../pages/manufacturing/WorkOrders.vue", import.meta.url)),
	"utf8",
);

/** The first `<thead>` — the register's own, not the materials sub-table's. */
function registerHead() {
	const open = src.indexOf("<thead>");
	return src.slice(open, src.indexOf("</thead>", open));
}

describe("the table shows what the strip counted", () => {
	it("renders the filtered view, not the raw row list", () => {
		// The whole point of the tabs. Iterating `rows` here would make every tab
		// show the same nine orders under three different badges.
		expect(src).toMatch(/v-for="r in visibleRows"/);
		expect(src).not.toMatch(/v-for="r in rows"/);
	});

	it("derives that view through the tested helper rather than inline", () => {
		expect(src).toMatch(/ledgerView\(rows\.value, view\.value, stock\.value, now\.value\)/);
		expect(src).toMatch(/shiftSummary\(rows\.value, stock\.value, now\.value\)/);
	});

	it("counts the badges off the same summary the tiles use", () => {
		// Three tabs, each reading its number from `ledger`. A hand-written
		// `rows.filter(...)` in the template would be a second implementation of
		// a rule that already has one.
		for (const key of ["ledger.orders", "ledger.ready", "ledger.overdue"]) {
			expect(src).toContain(key);
		}
	});
});

describe("the empty view explains itself", () => {
	it("spans exactly as many columns as the register has", () => {
		// Computed, not asserted against a literal: the next person to add a
		// column would otherwise leave a short row that renders as a ragged cell
		// and nobody would see it until it shipped.
		const columns = (registerHead().match(/<th[\s>]/g) || []).length;
		const colspan = Number(/<td colspan="(\d+)"/.exec(src)?.[1]);
		expect(columns).toBeGreaterThan(0);
		expect(colspan).toBe(columns);
	});

	it("says how many orders the register holds, not just that this view is empty", () => {
		// "Overdue: 0" is good news on this screen, and a bare empty frame reads
		// as a page that failed to load.
		expect(src).toMatch(/Nothing in this view/);
		expect(src).toContain("[ledger.orders]");
	});
});

describe("the line column is the third one, as designed", () => {
	it("sits between the product and the operators", () => {
		const head = registerHead();
		const order = ["Work Order", "Finished good", "Line", "Operators"].map((h) =>
			head.indexOf(`t("${h}")`),
		);
		expect(order.every((i) => i > -1)).toBe(true);
		expect([...order].sort((a, b) => a - b)).toEqual(order);
	});

	it("reads the WIP warehouse, because this factory has no workstations", () => {
		// Measured on anjan: 0 Workstation rows. The line filter above the table
		// already resolves a line to its WIP store; the column has to agree with
		// it or the filter and the column would name different things.
		expect(src).toContain("r.wip_warehouse");
	});
});

describe("the two figures the rows cannot answer", () => {
	it("are fetched from the endpoint built for them", () => {
		expect(src).toContain("stabler.api.manufacturing.wo_ledger_activity");
	});

	it("scope the scrap count to the orders on screen", () => {
		// `wo_ledger_activity` counts scrap for the work orders it is given. Not
		// passing them would make the tile describe the whole company under a
		// header that claims to describe this list.
		expect(src).toMatch(/work_orders:\s*JSON\.stringify\(rows\.value\.map/);
	});

	it("survive the endpoint failing", () => {
		// Two tiles out of five. A stop log that will not answer must not take
		// the register down with it.
		expect(src).toMatch(/activity\.value = null/);
	});
});

describe("a register left open across a shift keeps telling the time", () => {
	it("re-reads the clock on every load", () => {
		// `overdue` compares against `now`. Captured once at mount, a screen left
		// open on the shop floor would keep measuring against the hour it was
		// opened and stop reporting anything as late.
		expect(src).toMatch(/now\.value = new Date\(\)/);
	});
});

// ---------------------------------------------------------------------------
// Design 1b — «Канбан: состояние цеха».
//
// The state machine is pinned by `shopFloorBoard.spec.js`, which executes it.
// What is left here is again the wiring, and the board adds a failure this page
// did not have before: two renderings of one list. A board fed from `rows` while
// the tabs filter `visibleRows` would show every order under a tab that says 2,
// and both halves would still pass their own unit tests.

describe("the board draws the same orders the tabs selected", () => {
	it("groups the filtered view, not the raw row list", () => {
		expect(src).toMatch(/boardGroups\(visibleRows\.value\)/);
	});

	it("derives the columns through the tested helper rather than inline", () => {
		// A `rows.filter(r => r.docstatus === 0)` in the template would be a
		// second implementation of a precedence order that already has one, and
		// the two would disagree the first time a rule moved.
		expect(src).toMatch(/from "\.\.\/\.\.\/composables\/shopFloorBoard\.js"/);
		expect(src).not.toMatch(/docstatus === 0 \?/);
	});
});

describe("the board keeps its shape", () => {
	it("renders the columns the composable exports, in its order", () => {
		// Iterating `Object.keys(columns)` would work today and would silently
		// reorder the board the day the grouping object is built differently.
		expect(src).toMatch(/v-for="key in BOARD_COLUMNS"/);
	});

	it("labels every column the composable exports", () => {
		// Computed, not a literal list: a seventh column added to the composable
		// with no label here renders `COLUMN_LABELS[key]()` on undefined and takes
		// the whole page down with a TypeError. This test is the one place that
		// notices, because the two files are edited apart.
		const block = /const COLUMN_LABELS = \{([\s\S]*?)\n\};/.exec(src)?.[1] ?? "";
		const labelled = [...block.matchAll(/^\t(\w+):/gm)].map((m) => m[1]);
		expect(labelled).toEqual(BOARD_COLUMNS);
	});

	it("draws an empty column rather than dropping it", () => {
		// Measured on anjan 2026-08-29: `partial`, `running` and `paused` hold 0.
		// A board that hides empty bins becomes a three-bin board and hides
		// exactly the steps nobody is recording — which is the reason to show it.
		expect(src).toMatch(/v-if="!columns\[key\]\.length"/);
	});
});

describe("list and board are one register, not two", () => {
	it("shows exactly one of them", () => {
		// Chained onto the same v-if that already handles loading and empty. Two
		// independent `v-if`s would render the table under the board the moment
		// somebody edited one of them.
		const board = src.indexOf('v-else-if="layout === \'board\'"');
		const table = src.indexOf("<table class=\"table table-vcenter card-table table-hover\">");
		expect(board).toBeGreaterThan(-1);
		expect(src.slice(board, table)).toMatch(/<div v-else class="card">/);
	});

	it("routes a card to the order instead of dragging it", () => {
		// Nothing on this board is written by moving a card: `status` is read-only
		// after submit and every column is derived. A drag handle would promise a
		// state change the backend has no endpoint for.
		expect(src).toMatch(/name: 'manufacturing-work-order', params: \{ name: r\.name \}/);
		expect(src).not.toMatch(/draggable/);
	});
});
