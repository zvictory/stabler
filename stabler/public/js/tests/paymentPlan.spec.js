import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
	KIND_OPTIONS,
	KIND_EXTRA,
	CONFIDENCE_OPTIONS,
	directionOf,
	monthBounds,
	calendarEvents,
	runningBalance,
	monthSummary,
} from "../composables/paymentPlan.js";

const doctype = JSON.parse(
	readFileSync(
		fileURLToPath(new URL("../../../stabler/doctype/payment_plan_entry/payment_plan_entry.json", import.meta.url)),
		"utf-8",
	),
);
const field = (name) => doctype.fields.find((f) => f.fieldname === name);

describe("the kind list matches the doctype it writes to", () => {
	// The backend rejects an unknown kind, so a list that drifted would show the
	// user a button whose only outcome is a validation error — and a kind the
	// backend has but the form lacks is a plan nobody can enter.
	it("offers exactly the kinds the doctype accepts", () => {
		expect(KIND_OPTIONS.map((k) => k.value).sort()).toEqual(field("kind").options.split("\n").sort());
	});

	it("gives every kind a direction, and only In or Out", () => {
		for (const kind of KIND_OPTIONS) {
			expect(["In", "Out"]).toContain(kind.direction);
		}
	});

	it("decides an extra field for every kind", () => {
		// A kind missing from the map renders no second field at all, which reads
		// as a form that forgot to load rather than as a deliberate blank.
		expect(Object.keys(KIND_EXTRA).sort()).toEqual(KIND_OPTIONS.map((k) => k.value).sort());
	});

	it("offers the confidence levels the doctype stores", () => {
		expect(CONFIDENCE_OPTIONS.map((c) => c.value)).toEqual(field("confidence").options.split("\n"));
	});

	it("resolves a direction for a known kind", () => {
		expect(directionOf("Customer Receipt")).toBe("In");
		expect(directionOf("Salary")).toBe("Out");
	});
});

describe("monthBounds", () => {
	it("ends a 31-day month on the 31st", () => {
		expect(monthBounds("2026-08")).toEqual({ from: "2026-08-01", to: "2026-08-31" });
	});

	it("ends February on the 28th in a common year", () => {
		expect(monthBounds("2026-02").to).toBe("2026-02-28");
	});

	it("ends February on the 29th in a leap year", () => {
		// A hardcoded 28 loses a whole day of plans every four years, and only
		// every four years, which is the worst possible cadence for noticing.
		expect(monthBounds("2028-02").to).toBe("2028-02-29");
	});
});

describe("calendarEvents", () => {
	const rows = [
		{ name: "P1", due_date: "2026-08-04", direction: "In", amount: 1000, currency: "USD", party_name: "TVZ", status: "Planned" },
		{ name: "P2", due_date: "2026-08-04", direction: "Out", amount: 400, currency: "USD", party_name: "Rent", status: "Planned" },
		{ name: "P3", due_date: "2026-08-09", direction: "Out", amount: 200, currency: "USD", party_name: "Tax", status: "Realized" },
		{ name: "P4", due_date: "2026-08-11", direction: "Out", amount: 900, currency: "USD", party_name: "Gone", status: "Cancelled" },
	];

	it("shows money in and money out as different chips", () => {
		// This is the first thing a director reads off the grid; if both sides
		// render alike the calendar is just a list with dates.
		const [inflow, outflow] = calendarEvents(rows);
		expect(inflow.state).toBe("inflow");
		expect(outflow.state).toBe("outflow");
	});

	it("mutes a realized row instead of leaving it a question", () => {
		expect(calendarEvents(rows).find((e) => e.contractId === "P3").state).toBe("paid");
	});

	it("drops cancelled rows entirely", () => {
		expect(calendarEvents(rows).map((e) => e.contractId)).not.toContain("P4");
	});

	it("carries the row so a chip click opens the right one", () => {
		expect(calendarEvents(rows)[0].entry.name).toBe("P1");
	});

	it("ignores a row with no due date rather than drawing it on the epoch", () => {
		expect(calendarEvents([{ name: "X", due_date: null, direction: "Out" }])).toEqual([]);
	});
});

describe("runningBalance", () => {
	const days = [
		{ due_date: "2026-08-10", inflow: 0, outflow: 300 },
		{ due_date: "2026-08-03", inflow: 500, outflow: 100 },
		{ due_date: "2026-08-20", inflow: 100, outflow: 0 },
	];

	it("answers 'by the 20th, am I still above water'", () => {
		// A day's own net says nothing on its own — the carried total is the
		// question a planner actually brings to a calendar.
		expect(runningBalance(days).map((d) => d.balance)).toEqual([400, 100, 200]);
	});

	it("sorts by date regardless of the order the server answered in", () => {
		expect(runningBalance(days).map((d) => d.due_date)).toEqual(["2026-08-03", "2026-08-10", "2026-08-20"]);
	});

	it("starts from the opening balance it was given", () => {
		expect(runningBalance(days, 1000)[0].balance).toBe(1400);
	});

	it("does not mutate the array it was handed", () => {
		const input = [...days];
		runningBalance(input);
		expect(input[0].due_date).toBe("2026-08-10");
	});
});

describe("monthSummary", () => {
	const days = [
		{ due_date: "2026-08-03", inflow: 500, outflow: 100, entries: 2 },
		{ due_date: "2026-08-10", inflow: 0, outflow: 300, entries: 1 },
	];

	it("nets the month", () => {
		expect(monthSummary(days)).toMatchObject({ inflow: 500, outflow: 400, net: 100, entries: 3 });
	});

	it("names the heaviest paying day so nobody has to scan the grid for it", () => {
		expect(monthSummary(days).heaviest).toBe("2026-08-10");
	});

	it("survives an empty month", () => {
		expect(monthSummary([])).toMatchObject({ inflow: 0, outflow: 0, net: 0, heaviest: null });
	});
});
