import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

import { distributionLabel, receivedLabel } from "../composables/landedCostLabels.js";

const here = dirname(fileURLToPath(import.meta.url));

/**
 * H.2 (docs/backlog.md walk, 2026-09-05) — English strings measured live in the
 * Russian UI. Every key below was found already wrapped in t()/_() but missing
 * (or empty) in one or more of the five catalogues, or missing from all five.
 * This is the same catalogue-completeness idiom as tenderDimension.spec.js's
 * "ships every new string in all five catalogues" — reused rather than
 * reinvented, per this repo's own CSV-row test convention.
 */
function loadCatalog(lang) {
	const raw = readFileSync(resolve(here, `../../../translations/${lang}.csv`), "utf8");
	const rows = new Map();
	for (const line of raw.split("\n")) {
		if (!line) continue;
		const m = /^(?:"((?:[^"]|"")*)"|([^,]*)),(.*)$/.exec(line);
		if (!m) continue;
		const key = m[1] !== undefined ? m[1].replaceAll('""', '"') : m[2];
		let val = m[3];
		if (val.startsWith('"') && val.endsWith('"')) val = val.slice(1, -1).replaceAll('""', '"');
		rows.set(key, val);
	}
	return rows;
}

describe("H.2 -- ru-walk strings ship in all five catalogues", () => {
	const keys = [
		"New Purchase Invoice",
		"New Sales Order",
		"New purchase invoice",
		"Bill No.",
		"Bill Date",
		"Update stock",
		"Commercial Invoice (Import Attribution)",
		"Tax amount",
		"Add Row",
		"Add Item",
		"New Item",
		"Search…",
		"Submit document?",
		"Are you sure you want to submit this document? This will finalize transactions.",
		"You have unsaved changes. Leaving this page will discard them.",
		"Partially billed — {pct}% invoiced.",
		"Fulfilment & Billing",
		"Line details",
		"Ordered",
		"Billed amt",
		"Kind",
		"Send to Didox",
		"PO Created",
		"No expenses in this range",
		"Record an outgoing payment to start tracking spend.",
		"No landed-cost lines have been found.",
		"Exchange rate preview",
		"Spread the charges over",
		"By line value",
		"The voucher is created as a draft. Review it under Existing vouchers, then submit it there to post the valuation.",
		"Estimated Total",
		"Lot / Deal",
		"Parent Tender",
		"Total delivered cost",
		"Charge type",
		"Document saved successfully.",
		"Purchase Receipt submitted.",
		"We kindly ask you to quote your prices and delivery terms for the following items.",
		"Received ({0})",
		"Scope",
		"Evidence",
		"Price",
		// api/purchasing.py:2491,2497,2499,2507 (create_purchase_receipt_from_po) --
		// python _() keys land in the same five CSVs as the frontend t() keys.
		"Only submitted purchase orders can be received.",
		"Invalid items payload.",
		"Nothing left to receive on this purchase order.",
	];

	for (const lang of ["en", "ru", "uz", "uzc", "tr"]) {
		it(`${lang}.csv has a non-empty target for every key`, () => {
			const rows = loadCatalog(lang);
			for (const key of keys) {
				expect(rows.get(key), `${lang}.csv has no target for ${JSON.stringify(key)}`).toBeTruthy();
			}
		});
	}

	// "Юк хати" (Uzbek document name, Uzbek Cyrillic doctype label) is data, not a
	// translation gap -- it must stay exactly as the document itself spells it,
	// never picked up as a translatable source string.
	it("never turns the Uzbek document name 'Юк хати' into a translation key", () => {
		for (const lang of ["en", "ru", "uz", "uzc", "tr"]) {
			const rows = loadCatalog(lang);
			expect(rows.has("Юк хати")).toBe(false);
		}
	});
});

/**
 * H.3 -- the landed-cost review's distribution-basis label and its "Received"
 * weight/quantity label both hardcoded "(kg)" regardless of what the receipt
 * actually carries. ERPNext's own Landed Cost Voucher distributes "Qty" purely
 * proportional to the raw qty field (landed_cost_voucher.py:
 * set_applicable_charges_on_item, based_on_field = frappe.scrub(...)) -- it is
 * never weight-specific. "(kg)" was only ever true for the GRN-Checklist/
 * imports route, which pins stock UOM to Kg by construction
 * (receipt_math.STOCK_UOM). A plain Purchase Receipt landed-cost review has no
 * such guarantee and can receive in any UOM.
 */
describe("H.3 -- distributionLabel is unit-neutral for Qty", () => {
	it("labels ERPNext's Qty basis 'By quantity', not a hardcoded weight unit", () => {
		// Mutation check: if this reverts to `t("By weight (kg)")`, the assertion
		// below fails because "kg" is back in the string.
		expect(distributionLabel("Qty")).toBe("By quantity");
		expect(distributionLabel("Qty")).not.toMatch(/kg/i);
	});

	it("still labels the Amount basis by line value", () => {
		expect(distributionLabel("Amount")).toBe("By line value");
	});

	it("echoes back an unrecognised basis untouched (a Desk-frozen 'Distribute Manually')", () => {
		expect(distributionLabel("Distribute Manually")).toBe("Distribute Manually");
	});
});

describe("H.3 -- receivedLabel shows the line's real UOM", () => {
	it("fills the placeholder with whatever UOM the payload sent", () => {
		// "Litre", not "Kg": kg is special-cased below (review follow-up, P3) —
		// this test is only about the generic placeholder-fill path.
		expect(receivedLabel("Litre")).toBe("Received (Litre)");
	});

	it("is not hardcoded to Kg -- a Nos-denominated receipt reads Nos", () => {
		// This is the regression this whole finding is about: a non-import
		// Purchase Receipt whose items are counted, not weighed.
		expect(receivedLabel("Nos")).toBe("Received (Nos)");
		expect(receivedLabel("Nos")).not.toMatch(/kg/i);
	});
});

/**
 * H.2 follow-up (2026-09-05) -- the receipt-creation refusals in
 * api/purchasing.py. 628b204 wrapped four frappe.throw() calls in
 * create_purchase_receipt_from_po; the rest of that function and the whole of
 * its sibling create_purchase_receipt still raised raw f-strings, so a Russian
 * operator read "Row 2: qty must be greater than zero." in English whatever
 * language the request carried. Two things must hold for the fix to be real:
 *   1. every frappe.throw() in those two functions hands its text to _() as a
 *      string literal -- an f-string is interpolated before _() sees it, so no
 *      catalogue row can ever match it (tests/test_api_refusals_are_not_mute.py
 *      pins the same rule for _validation_error);
 *   2. every key those _() calls produce has a non-empty target in all five
 *      catalogues -- otherwise _() falls through to English exactly as before.
 * The two LandedCostReview.vue distribution hints ride along: t()-wrapped since
 * the page was written, but never given a row in any catalogue, en.csv included.
 */
const purchasingApi = readFileSync(resolve(here, "../../../api/purchasing.py"), "utf8");

function pyFunction(name) {
	const start = purchasingApi.indexOf(`\ndef ${name}(`);
	expect(start, `api/purchasing.py has no ${name}`).toBeGreaterThan(-1);
	const rest = purchasingApi.slice(start + 1);
	// The body ends at the next column-0 def (with or without its decorator);
	// nested defs are tab-indented and never match.
	const end = rest.search(/\n(?:@frappe\.whitelist\(\)\n)?def /);
	return end === -1 ? rest : rest.slice(0, end);
}

const RECEIPT_FUNCTIONS = ["create_purchase_receipt_from_po", "create_purchase_receipt"];

describe("H.2 follow-up -- receipt-creation refusals are translatable", () => {
	const keys = [
		// create_purchase_receipt_from_po -- the three keys 628b204 already wrapped are
		// pinned here too, so this list is that function's complete key set
		"Unknown Purchase Order: {0}",
		"Only submitted purchase orders can be received.",
		"Invalid items payload.",
		"Nothing left to receive on this purchase order.",
		"Row {0}: po_detail is required.",
		"Row {0}: qty must be greater than zero.",
		"These order rows have nothing pending to receive: {0}",
		// create_purchase_receipt
		"Supplier is required.",
		"Unknown supplier: {0}",
		"Warehouse is required — a receipt moves stock into it.",
		"Unknown warehouse: {0}",
		"At least one item is required.",
		"Row {0}: item is required.",
		"Row {0}: unknown item '{1}'.",
		"Row {0}: rate cannot be negative.",
		// LandedCostReview.vue distribution hint -- t()-wrapped, never catalogued
		"Stock UOM is Kg for imports, so by weight spreads the charges across the kilograms received. By line value spreads them in proportion to each line's amount. ERPNext calls these two bases Qty and Amount.",
		"By weight spreads the charges across the received quantity in stock UOM. By line value spreads them in proportion to each line's amount. ERPNext calls these two bases Qty and Amount.",
	];

	for (const fn of RECEIPT_FUNCTIONS) {
		it(`${fn} hands every frappe.throw() a _() literal, never an f-string or a concatenation`, () => {
			const body = pyFunction(fn);
			const calls = [...body.matchAll(/frappe\.throw\(\s*(\S*)/g)];
			expect(
				calls.length,
				`${fn} has no frappe.throw() at all -- did the function move?`
			).toBeGreaterThan(0);
			for (const [call, head] of calls) {
				expect(/^(?:frappe\.)?_\(/.test(head), `${fn}: ${call.trim()} bypasses _()`).toBe(true);
			}
		});

		it(`${fn} raises only keys this spec pins to the catalogues`, () => {
			const literals = [...pyFunction(fn).matchAll(/_\("((?:[^"\\]|\\.)*)"\)/g)].map((m) => m[1]);
			expect(literals.length, `${fn} has no _() literal to check`).toBeGreaterThan(0);
			for (const key of literals) {
				expect(
					keys,
					`${fn} raises ${JSON.stringify(key)} but the key list above does not pin it`
				).toContain(key);
			}
		});
	}

	for (const lang of ["en", "ru", "uz", "uzc", "tr"]) {
		it(`${lang}.csv has a non-empty target for every key`, () => {
			const rows = loadCatalog(lang);
			for (const key of keys) {
				expect(rows.get(key), `${lang}.csv has no target for ${JSON.stringify(key)}`).toBeTruthy();
			}
		});
	}
});

/**
 * Review follow-up (P3): `receivedLabel` still had two edge cases the H.3 fix
 * above did not cover. An empty UOM (no line has one yet) filled the
 * placeholder with nothing -- "Received ()". And "Kg", the exact literal
 * `received_uom` pins on the imports/GRN-Checklist route
 * (receipt_math.STOCK_UOM), filled the SAME generic placeholder key
 * ("Received ({0})") -- a key that IS translated on a non-English locale, so
 * the raw Latin "Kg" landed inside an otherwise-Cyrillic string:
 * "Принято (Kg)". "Received (kg)" is a separate, fully-translated key
 * GRNChecklistDetail.vue already renders for this exact UOM; reusing it
 * (rather than filling the placeholder) is what keeps the string one
 * language throughout.
 */
describe("H.3 -- receivedLabel's edge cases (review follow-up, P3)", () => {
	it("says plain 'Received' for an empty UOM, not 'Received ()'", () => {
		expect(receivedLabel("")).toBe("Received");
		expect(receivedLabel(undefined)).toBe("Received");
	});

	it("reuses the fully-translated 'Received (kg)' key for the imports route's pinned Kg UOM", () => {
		expect(receivedLabel("Kg")).toBe("Received (kg)");
	});

	it("matches kg case-insensitively, not only the exact pinned casing", () => {
		expect(receivedLabel("kg")).toBe("Received (kg)");
		expect(receivedLabel("KG")).toBe("Received (kg)");
	});
});
