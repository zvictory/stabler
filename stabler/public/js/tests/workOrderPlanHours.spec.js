// Wiring for the planning screen's hours form.
//
// The arithmetic is pinned by `planSchedule.spec.js` (JS) and
// `test_wo_plan_board` (the server's `schedule_window`). What is left is the
// composition in between — the page takes a day, two clock times and a checkbox
// and turns them into two datetimes — and that is where this feature can be
// silently wrong while both ends stay green.

import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";

const src = readFileSync(
	fileURLToPath(new URL("../pages/manufacturing/WorkOrderPlan.vue", import.meta.url)),
	"utf8",
);

describe("the form composes two datetimes out of four boxes", () => {
	it("puts the end on the next day only when the planner said so", () => {
		// An end earlier than the start is exactly what a planner produces by
		// typing 06:00 and meaning tomorrow. Rolling it forward on their behalf
		// would schedule a night nobody agreed to; ignoring the box would save an
		// overnight window ending fourteen hours before it starts.
		expect(src).toMatch(/sched\.value\.nextDay \? addDays\(sched\.value\.day, 1\) : sched\.value\.day/);
	});

	it("sends a blank end rather than leaving it out", () => {
		// Blank is how an end gets cleared, and clearing is the only way to take
		// back a mistyped one. Omitting the field would make the server keep the
		// old value and the box would look uneditable.
		expect(src).toMatch(/planned_end_date: sched\.value\.end \? .* : ""/);
	});

	it("loads the picked order's own hours into the boxes", () => {
		// Without this the form opens showing the PREVIOUS order's hours, and
		// pressing Save writes them onto this one.
		expect(src).toMatch(/if \(selected\.value\) openSchedule\(selected\.value\)/);
	});

	it("reads the overnight flag back off the dates", () => {
		// Remembered instead of derived, the flag resets to false on reopening and
		// the next save pulls the end a day earlier — a bug that only shows up on
		// the second edit.
		expect(src).toMatch(/nextDay: Boolean\(end\.day && start\.day && end\.day !== start\.day\)/);
	});
});

describe("one home for the stamp rules", () => {
	it("does not keep a second copy of the splitter", () => {
		// The page grew its own `splitStamp` before the composable existed. Two
		// copies of "which characters are the minute" drift, and the drift shows
		// up as a time box that silently refuses to fill.
		expect(src).toMatch(/from "\.\.\/\.\.\/composables\/planSchedule\.js"/);
		expect(src).not.toMatch(/function splitStamp/);
	});

	it("shows the typed hours back on the block", () => {
		// The whole point of the form. Without this the planner types hours and
		// the grid looks exactly as it did before.
		expect(src).toMatch(/scheduleLabel\(order\)/);
	});
});

// ---------------------------------------------------------------------------
// The day grid — design 1c's «линия × время».

describe("the day grid draws only what somebody planned", () => {
	it("gives a bar to an order with a typed end and a mark to one without", () => {
		// The whole honesty rule, and the one thing a screenshot of this screen
		// must not be able to lie about. A bar of any width where no end was typed
		// is a duration nobody stated — and there are 3 799 of those today.
		expect(src).toMatch(/v-if="b\.width !== null"/);
		expect(src).toMatch(/class="position-absolute plan-mark"/);
	});

	it("derives the rows through the tested composable", () => {
		expect(src).toMatch(/timelineRows\(dayOrders\.value, grid\.value\.lines \|\| \[\]\)/);
	});

	it("asks the server for one day when it is drawing one day", () => {
		// A week's rows on a one-day ruler would stack every order on top of the
		// same hours, and the grid would show collisions that do not exist.
		expect(src).toMatch(/mode\.value === "day" \? startDate\.value : addDays\(/);
	});

	it("steps by a day in day mode and by a week in week mode", () => {
		expect(src).toMatch(/n \* \(mode\.value === "day" \? 1 : WINDOW_DAYS\)/);
	});

	it("opens the hours form from a block", () => {
		// The grid and the form are one loop: the grid shows what is missing, the
		// form is how it gets filled. A block that only navigated away would break
		// it in the middle.
		// Both of them — the bar AND the mark. Asserting one occurrence let a
		// mutation replace the bar's handler and stay green, and the mark is the
		// half that matters most: it is the order that still needs hours.
		expect(src.match(/@click="pick\(b\.order, row\.line\)"/g) || []).toHaveLength(2);
	});

	it("keeps a mark out from under the bars", () => {
		// Measured on prod 2026-08-29, entering hours by hand: all four of the
		// day's orders sit on one line, and the mark for MFG-WO-2026-04178 landed
		// at 53.4% — inside MFG-WO-2026-04180's bar, which spans 43.8%–71.9%.
		// Sharing the track's full height, the mark is drawn under the bar:
		// invisible and unclickable, on exactly the order that still needs hours.
		// The two live in separate vertical bands now, and the CSS is the only
		// thing that keeps them apart.
		// Computed from the rules, not two pinned literals. The first version of
		// this test asserted `bottom: 1rem` and `top: 1.5rem` and passed while the
		// two bands still overlapped by 0.25rem — it pinned the numbers I happened
		// to write instead of the property they were meant to produce.
		// Comments stripped, and for the second time today: the rule this file
		// already learned on the mount hook. The comment explaining these bands
		// contains the words `bottom: 1rem`, so an un-stripped search read the
		// prose instead of the declaration and reported the old value.
		const css = src.replace(/\/\*[\s\S]*?\*\//g, "");
		const rem = (block, prop) => {
			const body = new RegExp(`\\.${block} \\{([\\s\\S]*?)\\}`).exec(css)?.[1] ?? "";
			const found = new RegExp(`${prop}:\\s*([\\d.]+)rem`).exec(body);
			return found ? Number(found[1]) : null;
		};
		const height = rem("plan-track", "height");
		const barBottomEdge = height - rem("plan-block", "bottom");
		const markTopEdge = rem("plan-mark", "top");
		expect(height).toBeGreaterThan(0);
		expect(markTopEdge).toBeGreaterThanOrEqual(barBottomEdge);
	});

	it("names the orders it could not place instead of dropping them", () => {
		expect(src).toMatch(/timeline\.offGrid\.length/);
	});
});
