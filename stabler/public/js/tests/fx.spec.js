import { describe, expect, it } from "vitest";

import { quotedLeg, readableRate, toLineRate } from "../composables/fx.js";

// The dominant Uzbek configuration: the company books in сўм, the expense is
// paid out of a USD account.
const BASE = "UZS";
const PAY = "USD";

// The Central Bank's quote for the day, the way an operator says it out loud
// and the way the CBU hint prints it: 1 USD = 12 953 сўм. This is also
// ERPNext's direction for the payment leg, and the one `submit_expense_entry`
// documents for its `exchange_rate` argument — base per 1 payment unit. The
// server does exactly `base_total = total_pay_amount * exchange_rate`
// (stabler/api/money.py), so this is the number that decides what lands in the
// ledger.
const LINE_RATE = 12953;

// The same fact upside down, and what
// `stabler.api.money.get_exchange_rate_for_currencies(UZS, USD)` returns:
// payment-currency units per 1 base unit. Unreadable on purpose — this is the
// number the Expense form used to put in a field labelled "1 USD =".
const API_QUOTE = 1 / LINE_RATE; // ≈ 0.0000772

describe("the rate an operator is shown is the rate the entry posts at", () => {
	// The defect this pins, measured: the Expense form built the readable quote
	// correctly — label "1 USD =", hint "CBU: 12 953" — and then put the RAW
	// 0.0000772 in the input beside it, rendered as USD with two decimals, so
	// the operator read "0.00". Correcting that to the 12 953 the label and the
	// hint both asked for posted a $100 expense as 100 × 1/12953 = 0.0077 сўм,
	// and the only cross-check on screen printed that as "0".
	it("posts $100 at 12 953 сўм/$ as 1 295 300 сўм, not as its reciprocal", () => {
		const quote = readableRate(LINE_RATE, PAY, BASE);
		expect(quote.strong).toBe("USD"); // the label reads "1 USD ="
		expect(quote.weak).toBe("UZS"); // ...so the input holds сўм

		// The operator types the number the label and the CBU hint both state.
		const typed = 12953;
		const leg = quotedLeg(typed, quote.strong, PAY, 100);

		// What goes on the wire, and what the server multiplies the $100 by.
		expect(leg.lineRate).toBe(12953);
		expect(100 * leg.lineRate).toBe(1295300);
		// What the form prints under the table, to the сўм — the same number,
		// because a preview that can disagree with the payload is not a check.
		expect(leg.baseAmount).toBe(1295300);
	});

	// The automatic path was already correct; what killed was that reading the
	// rate off the screen and typing it back changed the entry. It must not.
	it("survives being read off the screen and typed back in unchanged", () => {
		const quote = readableRate(LINE_RATE, PAY, BASE);
		const retyped = quotedLeg(quote.value, quote.strong, PAY, 100);
		expect(retyped.lineRate).toBeCloseTo(LINE_RATE, 9);
		expect(retyped.baseAmount).toBeCloseTo(100 * LINE_RATE, 6);
	});

	// Same pair, company booking in USD instead. The operator says the rate the
	// same way out loud, so the screen must state it the same way — and the
	// number they type has to mean the same thing in both books.
	it("reads '1 USD = 12 953 UZS' whichever side the company books in", () => {
		const mirrored = readableRate(API_QUOTE, "UZS", "USD");
		expect(mirrored.strong).toBe("USD");
		expect(mirrored.weak).toBe("UZS");
		expect(mirrored.value).toBe(12953);

		// A 1 295 300 сўм expense paid from a UZS account, USD-base company.
		const leg = quotedLeg(12953, mirrored.strong, "UZS", 1295300);
		expect(leg.lineRate).toBeCloseTo(1 / 12953, 12);
		expect(leg.baseAmount).toBeCloseTo(100, 6);
	});

	// `readableRate` is what keeps the input off "0.00": whichever way the pair
	// runs, the number in the field is the one ≥ 1.
	it("never puts a sub-unit rate in front of the operator", () => {
		expect(readableRate(LINE_RATE, PAY, BASE).value).toBeGreaterThanOrEqual(1);
		expect(readableRate(API_QUOTE, "UZS", "USD").value).toBeGreaterThanOrEqual(1);
	});

	// The rate lookup throws for a pair the Central Bank has no row for, and the
	// form then invites the operator to type the rate by hand. That invitation
	// is only safe if the label still states a direction, and states it for the
	// pair now on screen — a quote left over from the previous account is how a
	// rate gets applied to a currency it was never quoted for.
	it("still names a direction when no rate could be fetched", () => {
		const quote = readableRate(0, "EUR", BASE);
		expect(quote.strong).toBe("EUR");
		expect(quote.weak).toBe("UZS");
		expect(quote.value).toBe(0);
	});

	// The direction the user typed against is the one they were shown, not one
	// re-derived from their own number — the same rule JournalEntryDrawer keeps.
	it("reads the typed number against the direction on the label", () => {
		expect(toLineRate(12953, "USD", "USD")).toBe(12953);
		expect(toLineRate(12953, "USD", "UZS")).toBeCloseTo(1 / 12953, 12);
	});

	it("treats a blank or nonsense rate as no rate at all", () => {
		expect(quotedLeg(null, "USD", "USD", 100)).toEqual({ lineRate: 0, baseAmount: 0 });
		expect(quotedLeg(-3, "USD", "USD", 100)).toEqual({ lineRate: 0, baseAmount: 0 });
	});
});
