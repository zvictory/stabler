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
