import { describe, expect, it } from "vitest";
import { grossRate } from "../composables/pricing.js";

// The sales order editor has two prices per line and they are not the same
// number. The rate CELL holds the gross price — SalesOrderLines.vue's lineAmount
// applies the discount on top of it — while the saved document's `rate` is the
// net price ERPNext bills, with the gross kept in `price_list_rate`.
//
// Measured on anjan, SAL-ORD-2026-15847: 216 000 gross at 4 %.
const GROSS = 216000;
const NET = 207360; // 216 000 × 0.96 — what the document stores as `rate`

describe("reopening a document must not discount the line a second time", () => {
	// The failure this pins is silent and compounding: load 207 360 into a cell
	// the form treats as gross and the screen reads 199 065.60, which is 7.84 %
	// off — then saving writes THAT as the new net and the next open shows
	// 11.5 %. Nothing errors; the price just drains.
	it("reads back the gross price of a discounted line", () => {
		expect(grossRate({ rate: NET, price_list_rate: GROSS, discount_percentage: 4 })).toBe(GROSS);
	});

	it("re-derives the same net rate the document already holds", () => {
		const shown = grossRate({ rate: NET, price_list_rate: GROSS, discount_percentage: 4 });
		expect(shown * (1 - 4 / 100)).toBeCloseTo(NET, 6);
	});

	it("leaves an undiscounted line at its own rate", () => {
		expect(grossRate({ rate: GROSS, price_list_rate: GROSS })).toBe(GROSS);
	});
});

describe("a line with no usable list rate falls back to its own rate", () => {
	it("ignores a missing list rate", () => {
		expect(grossRate({ rate: GROSS })).toBe(GROSS);
		expect(grossRate({ rate: GROSS, price_list_rate: 0 })).toBe(GROSS);
	});

	// The documents this bug already wrote look like this: the full price was
	// billed as `rate` while `price_list_rate` holds the FX-converted catalogue
	// price, which lands slightly BELOW it. Trusting the lower number there
	// would quietly restate the price of every order placed before the fix.
	it("does not lower the rate of an already-written document", () => {
		expect(grossRate({ rate: 192000, price_list_rate: 191425.92, discount_percentage: 10 })).toBe(
			192000
		);
	});

	it("survives a missing line", () => {
		expect(grossRate(undefined)).toBe(0);
		expect(grossRate({})).toBe(0);
	});
});
