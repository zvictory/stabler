import { describe, expect, it } from "vitest";

import { getDocstatusLabel, getStatusBadgeClass } from "../composables/status.js";

// CLAUDE.md: "All status badges and labels must be resolved centrally using
// getStatusBadgeClass. No per-page status mappings." These tests guard the two
// properties that make that rule worth keeping -- a doctype's own colour wins,
// and nothing ever falls through to undefined.

describe("getStatusBadgeClass — doctype-specific mapping", () => {
	it("uses the doctype's own colour for its own vocabulary", () => {
		expect(getStatusBadgeClass("Proforma Invoice", "CONFIRMED")).toBe("bg-blue-lt");
		expect(getStatusBadgeClass("Purchase Order", "To Receive and Bill")).toBe("bg-yellow-lt");
		expect(getStatusBadgeClass("Sales Invoice", "Overdue")).toBe("bg-red-lt");
	});

	// The precedence is the point. "Draft" is grey almost everywhere, but a Promo
	// Plan draft is amber because it is a plan waiting on approval, not a stub.
	// If the generic table ever wins, that distinction disappears app-wide.
	it("prefers the doctype map over the generic one for the same word", () => {
		expect(getStatusBadgeClass("Promo Plan", "Draft")).toBe("bg-yellow-lt");
		expect(getStatusBadgeClass("Sales Invoice", "Draft")).toBe("bg-secondary-lt");
	});

	it("falls back to the generic map for a doctype with no entry", () => {
		expect(getStatusBadgeClass("Some Doctype Nobody Mapped", "Paid")).toBe("bg-green-lt");
		expect(getStatusBadgeClass("Some Doctype Nobody Mapped", "Overdue")).toBe("bg-red-lt");
	});

	// A badge with no class renders as unstyled text mid-table. Grey is the floor.
	it.each([
		["Sales Invoice", "A Status That Does Not Exist"],
		["Sales Invoice", ""],
		["Sales Invoice", null],
		["Sales Invoice", undefined],
	])("returns the neutral grey for (%p, %p)", (doctype, status) => {
		expect(getStatusBadgeClass(doctype, status)).toBe("bg-secondary-lt");
	});
});

// Bead stabler-exc. Before the "Vehicle Agreement" block existed, five of the
// seven lifecycle states hit the generic table, found nothing, and came back
// grey -- so the Operations portfolio strip drew a terminated agreement exactly
// like a live one. These tests fail if that block is deleted, and they fail if
// someone collapses two states that the business needs to tell apart.
describe("getStatusBadgeClass — Vehicle Agreement lifecycle", () => {
	const VA = (s) => getStatusBadgeClass("Vehicle Agreement", s);

	// The five that used to fall through. Naming them individually means the
	// failure message says WHICH state regressed.
	it.each(["Review", "Approved", "Active", "Restructured", "Terminated"])(
		"resolves %s to something other than the fall-through grey",
		(state) => {
			expect(VA(state)).not.toBe("bg-secondary-lt");
		},
	);

	// The defect this bead was filed for, stated as an assertion.
	it("does not draw a terminated agreement like a live one", () => {
		expect(VA("Terminated")).not.toBe(VA("Active"));
	});

	// Completed is green by convention across this map, so Active must not be.
	// Otherwise the lifecycle strip overstates the live portfolio by every
	// agreement that already paid itself off.
	it("does not draw a settled agreement like a live one", () => {
		expect(VA("Completed")).toBe("bg-green-lt");
		expect(VA("Active")).not.toBe(VA("Completed"));
	});

	// A rescheduled agreement is an exception to watch. Green would hide the
	// risk the reschedule was taken on to avoid.
	it("marks Restructured as an exception rather than a healthy state", () => {
		expect(VA("Restructured")).toBe("bg-orange-lt");
		expect(VA("Restructured")).not.toBe(VA("Active"));
	});

	it("still greys a state that is not part of the lifecycle", () => {
		expect(VA("Repossessed")).toBe("bg-secondary-lt");
	});
});

describe("getStatusBadgeClass — numeric docstatus", () => {
	// A numeric argument is Frappe's docstatus, not a status name, and it must
	// short-circuit before the doctype lookup: several maps have string keys that
	// would coerce.
	it("maps docstatus ahead of any doctype map", () => {
		expect(getStatusBadgeClass("Sales Invoice", 0)).toBe("bg-yellow-lt");
		expect(getStatusBadgeClass("Sales Invoice", 1)).toBe("bg-green-lt");
		expect(getStatusBadgeClass("Sales Invoice", 2)).toBe("bg-red-lt");
	});

	it("greys out a docstatus Frappe does not define", () => {
		expect(getStatusBadgeClass("Sales Invoice", 7)).toBe("bg-secondary-lt");
	});

	// "0" from a query string is NOT docstatus 0 -- it takes the string path.
	// Documented here so the distinction is deliberate rather than accidental.
	it('does not treat the string "0" as a docstatus', () => {
		expect(getStatusBadgeClass("Sales Invoice", "0")).toBe("bg-secondary-lt");
	});
});

describe("getDocstatusLabel", () => {
	// Goes through t(), so it is translated. The fixture in tests/setup.js is
	// Russian precisely so a hardcoded English label would fail here.
	it("translates the three docstatus values", () => {
		expect(getDocstatusLabel(0)).toBe("Черновик");
		expect(getDocstatusLabel(1)).toBe("Проведён");
		expect(getDocstatusLabel(2)).toBe("Отменён");
	});

	it("stringifies anything outside 0/1/2 rather than returning undefined", () => {
		expect(getDocstatusLabel(9)).toBe("9");
		expect(getDocstatusLabel(null)).toBe("null");
	});
});
