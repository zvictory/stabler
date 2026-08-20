import { describe, expect, it } from "vitest";
import { currencyLegs, routeDeskLabel, routeLabel } from "../composables/remittanceRoute.js";

/**
 * A remittance route is written in exactly one way, on purpose.
 *
 * Two screens render it — the quote panel on New Transfer and the Operations
 * table (stabler-t1j9) — and before this module existed they disagreed: the
 * panel had no route row at all, and Operations stacked `branch -> branch` over
 * `city -> city` on two lines. These tests pin the format so the second caller
 * cannot quietly introduce a third spelling.
 */
describe("how one desk is written", () => {
	it("leads with the city, which is the opposite of the desk selector", () => {
		// NewRemittance's own `deskLabel` writes `TAS-C — Tashkent` for the
		// SELECTOR, where the cashier is picking a branch code. A route is read as
		// places before codes, so this order is deliberate and not a mistake to be
		// tidied up into agreement with the other one.
		expect(routeDeskLabel({ branch: "TAS-C", city: "Tashkent" })).toBe("Tashkent · TAS-C");
	});

	it("renders whichever half exists when a desk has no city", () => {
		// A Remittance Cash Desk Account row may carry no city — the field is not
		// mandatory — and the branch alone still identifies the desk.
		expect(routeDeskLabel({ branch: "IST-1", city: "" })).toBe("IST-1");
		expect(routeDeskLabel({ branch: "", city: "Istanbul" })).toBe("Istanbul");
	});

	it("says nothing about a desk it was not given", () => {
		expect(routeDeskLabel(null)).toBe("");
		expect(routeDeskLabel({ branch: "", city: "" })).toBe("");
	});
});

describe("how the two ends are joined", () => {
	it("writes the full route the design of record specifies", () => {
		expect(
			routeLabel({ branch: "TAS-C", city: "Tashkent" }, { branch: "IST-1", city: "Istanbul" })
		).toBe("Tashkent · TAS-C → Istanbul · IST-1");
	});

	it("still renders a half-known route rather than hiding it", () => {
		// The destination is chosen before the quote is complete, and on New
		// Transfer the origin is resolved asynchronously from the employee record.
		// Returning "" here would blank the row mid-form and read as "no route" on
		// a transfer that has one.
		expect(routeLabel(null, { branch: "IST-1", city: "Istanbul" })).toBe("— → Istanbul · IST-1");
		expect(routeLabel({ branch: "TAS-C", city: "Tashkent" }, null)).toBe("Tashkent · TAS-C → —");
	});

	it("returns empty when neither end is known, so the caller can drop the row", () => {
		// Distinct from the case above: a lone arrow between two dashes is not
		// information, and the quote panel renders "—" for the whole row instead.
		expect(routeLabel(null, null)).toBe("");
	});
});

describe("the currency legs under the route", () => {
	it("names both legs when they differ", () => {
		expect(currencyLegs("USD", "EUR")).toBe("USD → EUR");
	});

	it("says nothing when the two legs are the same currency", () => {
		// Same-currency transfers are ordinary in this module (appliedRate is then
		// the identity, 1). `USD → USD` reads as a bug to the cashier rather than
		// as a fact about the transfer.
		expect(currencyLegs("USD", "USD")).toBe("");
	});

	it("says nothing before both currencies are known", () => {
		expect(currencyLegs("USD", "")).toBe("");
		expect(currencyLegs("", "EUR")).toBe("");
	});

	it("uses the same arrow as the route, so the two lines read as one block", () => {
		// They are rendered one under the other. Two different arrows would look
		// like two different kinds of relationship.
		const arrowInRoute = routeLabel({ branch: "A" }, { branch: "B" }).replace(/[AB]/g, "").trim();
		const arrowInLegs = currencyLegs("USD", "EUR").replace(/USD|EUR/g, "").trim();
		expect(arrowInLegs).toBe(arrowInRoute);
	});
});
