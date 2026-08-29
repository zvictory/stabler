// The hours a planner types, and how the board reads them back.
//
// Design 1c needs a position and a width per block. Measured on anjan
// 2026-08-29 it has neither: 3 464 of 3 799 orders carry a `planned_start_date`
// within 60 seconds of `creation` — ERPNext's default, the moment the form was
// opened — and 0 carry a `planned_end_date` at all. These two functions are the
// small end of fixing that: one splits a stored stamp into the boxes a planner
// edits, the other renders what they typed back onto the block.

import { describe, it, expect } from "vitest";
import { splitStamp, scheduleLabel } from "../composables/planSchedule.js";

describe("splitting a stored stamp into the boxes that edit it", () => {
	it("takes the day and the minute, and drops the seconds", () => {
		// `<input type="time">` will not accept seconds, and the stored value
		// carries them (and microseconds, on every row this site has written).
		expect(splitStamp("2026-08-30 08:15:00.123456")).toEqual({ day: "2026-08-30", time: "08:15" });
	});

	it("gives empty boxes for something that is not a stamp at all", () => {
		// Not hypothetical bookkeeping: the guard reads the SHAPE, and a truthiness
		// check in its place passes every test above while slicing "tomorrow" into
		// a day box that reads `tomorro`. Measured — that mutation stayed green
		// until this case existed.
		expect(splitStamp("tomorrow")).toEqual({ day: "", time: "" });
		expect(splitStamp("30.08.2026 08:00")).toEqual({ day: "", time: "" });
	});

	it("gives empty boxes for an absent stamp rather than the string 'null'", () => {
		// 0 orders carry a planned end today, so this is the ordinary case, not
		// the edge one: the end box opens empty on essentially every order.
		for (const absent of [null, undefined, ""]) {
			expect(splitStamp(absent)).toEqual({ day: "", time: "" });
		}
	});
});

describe("what the block says about its hours", () => {
	it("shows the window when both ends are known", () => {
		expect(
			scheduleLabel({ planned_start_date: "2026-08-30 08:00:00", planned_end_date: "2026-08-30 14:30:00" }),
		).toBe("08:00–14:30");
	});

	it("shows the start alone when there is no end", () => {
		// A start with no end is a real plan — somebody said when this runs and
		// not for how long — and it has to read as that rather than as missing.
		expect(scheduleLabel({ planned_start_date: "2026-08-30 08:00:00" })).toBe("08:00");
	});

	it("marks an end that lands on another day", () => {
		// Without the marker, an overnight window reads as ending fourteen hours
		// BEFORE it starts, which is the one thing this label must never say.
		expect(
			scheduleLabel({ planned_start_date: "2026-08-30 22:00:00", planned_end_date: "2026-08-31 06:00:00" }),
		).toBe("22:00–06:00+1");
	});

	it("says nothing at all when there is no start", () => {
		// Empty, not a dash: the badge already carries the item and the quantity,
		// and a dash under every one of them is furniture on 3 799 rows.
		expect(scheduleLabel({})).toBe("");
		expect(scheduleLabel(null)).toBe("");
	});
});
