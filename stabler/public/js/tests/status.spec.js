import { describe, expect, it } from "vitest";

import {
	STATUS_MAP,
	getDocstatusLabel,
	getStatusBadgeClass,
	resolveBadgeClass,
} from "../composables/status.js";

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
	it.each(["Review", "Approved", "Active", "Rescheduled", "Restructured", "Terminated"])(
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
	it("marks Rescheduled as an exception rather than a healthy state", () => {
		expect(VA("Rescheduled")).toBe("bg-orange-lt");
		expect(VA("Rescheduled")).not.toBe(VA("Active"));
	});

	// Rescheduled and Restructured are NOT synonyms: the first is collectible
	// (same total, new schedule), the second is terminal on the original
	// agreement once a successor is opened. Sharing a colour would put a closed
	// contract and a live one in the same bucket on the lifecycle strip — the
	// exact confusion the vocabulary split was made to end.
	it("does not draw a restructured agreement like a rescheduled one", () => {
		expect(VA("Restructured")).not.toBe(VA("Rescheduled"));
	});

	// Terminal, but neither settled nor failed — so it must not borrow the
	// colour of either, or the restructure count reads as churn or as revenue.
	it("does not draw a restructured agreement like a settled or failed one", () => {
		expect(VA("Restructured")).not.toBe(VA("Completed"));
		expect(VA("Restructured")).not.toBe(VA("Terminated"));
	});

	it("still greys a state that is not part of the lifecycle", () => {
		expect(VA("Repossessed")).toBe("bg-secondary-lt");
	});
});

// Payment health is a SECOND axis, derived in api/vehicle_finance/read.py at two
// granularities: the agreement (Not Started/Current/Partial/Overdue/Paid) and the
// individual schedule row (Upcoming/Partial/Overdue/Paid). Both go through one
// map because the agreement badge in the list and the row badges in the preview
// drawer sit inches apart.
describe("getStatusBadgeClass — Vehicle Finance payment health", () => {
	const PH = (s) => getStatusBadgeClass("Vehicle Finance Payment Health", s);

	it.each(["Not Started", "Current", "Upcoming", "Partial", "Overdue", "Paid"])(
		"resolves %s without falling through to the generic map",
		(state) => {
			expect(STATUS_MAP["Vehicle Finance Payment Health"]).toHaveProperty(state);
		},
	);

	// The whole reason the badge exists: an operator scanning the list has to be
	// able to separate money that is late from money that is merely not due yet.
	it("does not draw an overdue agreement like a healthy one", () => {
		expect(PH("Overdue")).toBe("bg-red-lt");
		expect(PH("Overdue")).not.toBe(PH("Current"));
		expect(PH("Overdue")).not.toBe(PH("Paid"));
	});

	// Paid is green across this map, so Current and Upcoming must not be, or a
	// portfolio with nothing collected yet reads as a portfolio that is settled.
	it("does not draw money still owed like money already in", () => {
		expect(PH("Paid")).toBe("bg-green-lt");
		expect(PH("Current")).not.toBe(PH("Paid"));
		expect(PH("Upcoming")).not.toBe(PH("Paid"));
	});

	// The two granularities describe the same idea — not due yet — and are shown
	// side by side, so disagreeing on the colour would be a defect in itself.
	it("agrees with itself across the agreement and row vocabularies", () => {
		expect(PH("Current")).toBe(PH("Upcoming"));
	});

	// Not Started is an absence, not a state of health: there is nothing to pay
	// against until the agreement is activated.
	it("greys an agreement that has nothing to pay against yet", () => {
		expect(PH("Not Started")).toBe("bg-secondary-lt");
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

// --- resolveBadgeClass: the colour must come from the same fact as the text ---
//
// P0-SI-8. `FormPage` printed `t(status)` as the badge's text but asked for its
// colour with `docstatus`, and every submitted document has docstatus 1, which
// the docstatus table paints green. So an invoice reading "Overdue" was drawn
// in the same green as one reading "Paid". Measured on prod 2026-08-21: 2 812
// Overdue + 343 Unpaid + 8 Partly Paid + 22 Credit Note Issued on anjan alone,
// and 984 Overdue on msa -- every one of them green.
//
// The rule is not "prefer status". It is that a badge states ONE fact, so the
// colour and the word must be derived from the same input. docstatus is the
// fallback only because a document with no status string has nothing else.
describe("resolveBadgeClass — colour follows the word the badge shows", () => {
	it("paints a submitted-but-overdue invoice red, not submitted-green", () => {
		expect(resolveBadgeClass("Sales Invoice", "Overdue", 1)).toBe("bg-red-lt");
		expect(resolveBadgeClass("Sales Invoice", "Unpaid", 1)).toBe("bg-yellow-lt");
		expect(resolveBadgeClass("Sales Invoice", "Paid", 1)).toBe("bg-green-lt");
	});

	// Green for "Paid" and green for "Overdue" is worse than no colour at all:
	// it is a signal that actively contradicts the text next to it.
	it("never lets two opposite statuses share a colour", () => {
		const paid = resolveBadgeClass("Sales Invoice", "Paid", 1);
		const overdue = resolveBadgeClass("Sales Invoice", "Overdue", 1);
		expect(paid).not.toBe(overdue);
	});

	// The doctype key has to be a real doctype. FormPage passed `props.title` --
	// a translated heading ("Счёт-фактура продажи", "New Sales Order") -- so the
	// doctype table was unreachable and these two fell through to grey.
	it("reaches the doctype table for vocabulary the generic table lacks", () => {
		expect(resolveBadgeClass("Sales Invoice", "Credit Note Issued", 1)).toBe("bg-purple-lt");
		expect(resolveBadgeClass("Sales Invoice", "Partly Paid", 1)).toBe("bg-blue-lt");
	});

	// A document that carries no status string still has to render something.
	it.each([
		[0, "bg-yellow-lt"],
		[1, "bg-green-lt"],
		[2, "bg-red-lt"],
	])("falls back to docstatus %p when there is no status word", (docstatus, cls) => {
		expect(resolveBadgeClass("Sales Invoice", "", docstatus)).toBe(cls);
		expect(resolveBadgeClass("Sales Invoice", null, docstatus)).toBe(cls);
	});

	// Neither input present: grey, never undefined -- an unstyled badge is a
	// bare word floating in a card header.
	it("returns the neutral grey when it has nothing to go on", () => {
		expect(resolveBadgeClass("Sales Invoice", "", null)).toBe("bg-secondary-lt");
	});
});
