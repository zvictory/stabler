import { describe, expect, it } from "vitest";
import { priceListRateForOrder, quotedLeg, readableRate, toLineRate } from "../composables/fx.js";

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

// What the price-list lookup (`stabler.api.sales.get_item_price` /
// `item_sales_meta`) hands the form back. `currency` describes
// `price_list_rate` and nothing else — that is the whole API contract this
// function leans on.
const priced = (over = {}) => ({ price_list_rate: 1210185, currency: "UZS", unresolved: false, ...over });

// The live rate the form holds, quoted as "1 `from` = `rate` × `to`" — the
// same direction ERPNext stores `conversion_rate` in.
const quote = (over = {}) => ({ rate: 12101.85, from: "USD", to: "UZS", ...over });

describe("priceListRateForOrder — what number lands in a sales order's rate field", () => {
	// THE defect. A price list quoted in UZS, used on an order denominated in
	// USD: the form read `price_list_rate` and wrote it into the rate field
	// without ever reading the currency it was quoted in. 1 210 185 (so'm)
	// became 1 210 185 USD — or, seen from the other side, a 100 USD line was
	// invoiced at whatever the so'm figure happened to be. At the prevailing
	// rate that is a ~12 000× error on every foreign-currency order that takes
	// a price-list rate, and it lands in the customer's favour.
	it("converts a UZS price list onto a USD order instead of writing the so'm figure", () => {
		const out = priceListRateForOrder(priced(), "USD", quote(), 0);
		expect(out.rate).toBe(100);
		expect(out.unconverted).toBeUndefined();
	});

	// The other half of the same rule, and the one that makes the fix safe: if
	// no rate is known there is no honest conversion, so nothing is written.
	// Silently storing an unconverted number is the defect above; storing a
	// number converted at a guessed rate is the same defect wearing a hat.
	// The caller keeps the fallback and raises the warning banner.
	it("refuses to price the line when no exchange rate is known", () => {
		const out = priceListRateForOrder(priced(), "USD", quote({ rate: 0 }), 7);
		expect(out.unconverted).toBe(true);
		expect(out.rate).toBe(7);
	});

	// The no-guessing rule. The previous implementation defaulted a missing
	// price-list currency to "UZS" — a hardcoded currency default in money
	// code, which is the class of thing that put 675 purchase invoices on msa
	// at a rate that was not their own date's rate. On a USD-base tenant that
	// default would have divided a correct USD price by ~12 000. If we do not
	// know what currency the number is quoted in, we do not know what the
	// number means, and we must not write it into a currency-denominated field.
	it("refuses when the price list currency is unknown rather than assuming one", () => {
		const out = priceListRateForOrder(priced({ currency: null }), "USD", quote(), 7);
		expect(out.unconverted).toBe(true);
		expect(out.rate).toBe(7);
	});

	// Refusing has to stay narrow, or the form stops pricing anything. When the
	// price list is already quoted in the order's currency there is nothing to
	// convert and no rate is needed — not even a correct one.
	it("passes a same-currency price straight through, with no rate involved", () => {
		const out = priceListRateForOrder(priced({ currency: "USD", price_list_rate: 100 }), "USD", quote({ rate: 0 }), 0);
		expect(out.rate).toBe(100);
		expect(out.unconverted).toBeUndefined();
	});

	// The mirror direction, which is not symmetric with the first case: a USD
	// price list on an order written in the company's own so'm. The order has
	// no exchange rate of its own here (ERPNext stores 1 when the transaction
	// currency is the base currency), so the form quotes the pair against the
	// Central Bank's dollar rate instead, and this multiplies rather than
	// divides. Getting the direction from the pair — never from which number
	// looks bigger — is the point.
	it("converts a USD price list onto a so'm order by multiplying", () => {
		const out = priceListRateForOrder(priced({ currency: "USD", price_list_rate: 100 }), "UZS", quote(), 0);
		expect(out.rate).toBe(1210185);
	});

	// Direction must come from the pair's own labels even when the rate is
	// below 1, where "the bigger number is the strong currency" stops being
	// true. An earlier hand-rolled version of this rule decided direction with
	// a `currency === "UZS"` literal and inverted RUB-document/USD-book pairs
	// (rate ≈ 0.011); composables/fx.js exists so that literal has exactly one
	// place it cannot come back to. Both ways round, same pair.
	it("takes the direction from the pair, not the magnitude, on a sub-1 rate", () => {
		const rub = { rate: 0.011, from: "RUB", to: "USD" };
		expect(priceListRateForOrder(priced({ currency: "RUB", price_list_rate: 9000 }), "USD", rub, 0).rate).toBe(99);
		expect(priceListRateForOrder(priced({ currency: "USD", price_list_rate: 100 }), "RUB", rub, 0).rate).toBe(
			9090.9091
		);
	});

	// A price list in a third currency cannot be reached with the single rate
	// the form holds. Chaining two rates through an implied cross would invent
	// precision nobody quoted, so this refuses like the missing-rate case.
	it("refuses a third currency the form holds no rate for", () => {
		const out = priceListRateForOrder(priced({ currency: "EUR", price_list_rate: 90 }), "USD", quote(), 5);
		expect(out.unconverted).toBe(true);
		expect(out.rate).toBe(5);
	});

	// "No price found" is not a currency problem and must not raise the
	// currency warning — the caller falls back to the item's standard rate
	// exactly as before. Warning on this path would cry wolf on every tenant
	// that keeps no price list, and a warning nobody can act on is a warning
	// nobody reads.
	it("falls back quietly when the lookup resolved no price", () => {
		expect(priceListRateForOrder(priced({ unresolved: true }), "USD", quote(), 42)).toEqual({ rate: 42 });
		expect(priceListRateForOrder(priced({ price_list_rate: 0 }), "USD", quote(), 42)).toEqual({ rate: 42 });
		expect(priceListRateForOrder(null, "USD", quote(), 42)).toEqual({ rate: 42 });
	});

	// The rate field is stored at 4 decimals; converting at full float
	// precision and letting the server round produces a rate the user never
	// saw. Round where the number is made.
	it("rounds the converted rate to the 4 decimals the field stores", () => {
		const out = priceListRateForOrder(priced({ price_list_rate: 1000000 }), "USD", quote(), 0);
		expect(out.rate).toBe(82.632);
	});
});
