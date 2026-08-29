// Design 1c's grid — line × time, one day.
//
// The grid was left unbuilt on 2026-08-29 and the reason was measured: a block
// needs a position and a width, and anjan records neither. 3 464 of 3 799
// orders carry a `planned_start_date` within 60 seconds of `creation` (ERPNext
// writes it when the form opens — it is not a plan) and 0 carry a
// `planned_end_date`. A grid drawn from those defaults renders perfectly and
// charts data entry while looking exactly like a schedule.
//
// This module builds the grid without inventing either number. The rule that
// makes that possible is the one every test below circles: A BLOCK GETS A WIDTH
// ONLY WHEN AN END WAS TYPED. An order with a start and no end is drawn as a
// mark at its hour — visible, clickable, and honest that nobody has said how
// long it runs. The grid therefore starts almost empty and fills as the hours
// form is used, which is what it is for.

import { describe, it, expect } from "vitest";
import { dayWindow, blockGeometry, timelineRows } from "../composables/planTimeline.js";

const at = (start, end = null) => ({
	name: "WO-1",
	wip_warehouse: "Line 1",
	planned_start_date: start,
	planned_end_date: end,
});

describe("the hours the ruler covers", () => {
	it("is a working day when nothing is scheduled", () => {
		// An empty day still needs a ruler: a grid with no columns reads as a
		// screen that failed to load, and the planner has nowhere to aim at.
		expect(dayWindow([])).toEqual({ from: 6, to: 22 });
		expect(dayWindow(null)).toEqual({ from: 6, to: 22 });
	});

	it("opens earlier for an order that starts before it", () => {
		// Measured on anjan: orders are opened from 08:07 to 21:54, but the
		// earliest on record is 06:53 — an order outside a fixed ruler would be
		// drawn off the left edge, or clamped onto an hour it does not run at.
		expect(dayWindow([at("2026-08-30 05:30:00")])).toEqual({ from: 5, to: 22 });
	});

	it("closes later for an order that runs past it", () => {
		expect(dayWindow([at("2026-08-30 08:00:00", "2026-08-30 23:30:00")])).toEqual({ from: 6, to: 24 });
	});

	it("stops at midnight for a job that crosses it", () => {
		// The row is one day wide. An overnight job is drawn to the edge and
		// marked, never wrapped around to the left — a block that reappears at
		// 00:00 reads as a second job.
		expect(dayWindow([at("2026-08-30 22:00:00", "2026-08-31 06:00:00")])).toEqual({ from: 6, to: 24 });
	});

	it("ignores an order with no hour at all", () => {
		expect(dayWindow([at(null), at("")])).toEqual({ from: 6, to: 22 });
	});
});

describe("where a block sits and how wide it is", () => {
	const win = { from: 6, to: 22 }; // 16 hours across

	it("places a block at its start hour", () => {
		// 08:00 is two hours into a sixteen-hour ruler.
		const g = blockGeometry(at("2026-08-30 08:00:00", "2026-08-30 12:00:00"), win);
		expect(g.left).toBeCloseTo(12.5, 4);
		expect(g.width).toBeCloseTo(25, 4);
	});

	it("counts the minutes, not just the hour", () => {
		const g = blockGeometry(at("2026-08-30 08:30:00", "2026-08-30 09:00:00"), win);
		expect(g.left).toBeCloseTo((2.5 / 16) * 100, 4);
		expect(g.width).toBeCloseTo((0.5 / 16) * 100, 4);
	});

	it("gives NO width to an order whose end nobody typed", () => {
		// The rule the whole module exists for. A default duration here — an
		// hour, a shift, an average — would draw 3 799 bars nobody planned, and
		// the screen would be read as a schedule.
		const g = blockGeometry(at("2026-08-30 08:00:00"), win);
		expect(g.width).toBeNull();
		expect(g.left).toBeCloseTo(12.5, 4);
	});

	it("draws an overnight job to the edge and says so", () => {
		const g = blockGeometry(at("2026-08-30 22:00:00", "2026-08-31 06:00:00"), { from: 6, to: 24 });
		expect(g.left).toBeCloseTo((16 / 18) * 100, 4);
		expect(g.width).toBeCloseTo((2 / 18) * 100, 4);
		expect(g.overnight).toBe(true);
	});

	it("keeps a very short job wide enough to see and to click", () => {
		// A six-minute job on a sixteen-hour ruler is 0.6% wide — a sliver nobody
		// can hit. The floor is a drawing decision and is declared as one:
		// `width` is what is drawn, `hours` carries the truth for the label.
		const g = blockGeometry(at("2026-08-30 08:00:00", "2026-08-30 08:06:00"), win);
		expect(g.width).toBeGreaterThanOrEqual(1.5);
		expect(g.hours).toBeCloseTo(0.1, 4);
	});

	it("refuses to place an order with no start", () => {
		expect(blockGeometry(at(null), win)).toBeNull();
	});

	it("refuses an end equal to the start", () => {
		// The boundary, and it is the one the data actually contains: 354 of the
		// 434 orders finished in the last 30 days have `actual_end == actual_start`.
		// Zero hours is not a zero-width bar, it is an end nobody really recorded —
		// and `< 0` in place of `<= 0` passes every other test in this file.
		const g = blockGeometry(at("2026-08-30 08:00:00", "2026-08-30 08:00:00"), win);
		expect(g.width).toBeNull();
		expect(g.hours).toBeNull();
	});

	it("refuses an end that is not after the start", () => {
		// The server already rejects this on the way in. Data written before that
		// endpoint existed, or by the Desk, still has to not draw backwards.
		const g = blockGeometry(at("2026-08-30 14:00:00", "2026-08-30 08:00:00"), win);
		expect(g.width).toBeNull();
	});
});

describe("the rows of the grid", () => {
	it("keeps a line that has nothing on it", () => {
		// Same rule as the board's empty columns: a row that disappears when it is
		// idle hides the fact that the line is idle, which is what a planner is
		// looking for.
		const rows = timelineRows([], ["Line 1", "Line 2"]);
		expect(rows.rows.map((r) => r.line)).toEqual(["Line 1", "Line 2"]);
		expect(rows.rows[0].blocks).toEqual([]);
	});

	it("puts each order on its own line, in start order", () => {
		const orders = [
			{ ...at("2026-08-30 14:00:00"), name: "B" },
			{ ...at("2026-08-30 08:00:00"), name: "A" },
			{ ...at("2026-08-30 09:00:00"), name: "C", wip_warehouse: "Line 2" },
		];
		const rows = timelineRows(orders, ["Line 1", "Line 2"]);
		expect(rows.rows[0].blocks.map((b) => b.order.name)).toEqual(["A", "B"]);
		expect(rows.rows[1].blocks.map((b) => b.order.name)).toEqual(["C"]);
	});

	it("hands back an order whose line is not on the grid", () => {
		// Not dropped: it is work somebody scheduled, and a grid that claims to
		// show the day has to account for it. Same contract as `build_plan_grid`.
		const rows = timelineRows([{ ...at("2026-08-30 08:00:00"), wip_warehouse: "Line 9" }], ["Line 1"]);
		expect(rows.rows[0].blocks).toEqual([]);
		expect(rows.offGrid.map((o) => o.wip_warehouse)).toEqual(["Line 9"]);
	});

	it("hands back an order with no hour rather than pinning it to 00:00", () => {
		const rows = timelineRows([{ ...at(null), name: "Z" }], ["Line 1"]);
		expect(rows.rows[0].blocks).toEqual([]);
		expect(rows.offGrid.map((o) => o.name)).toEqual(["Z"]);
	});
});
