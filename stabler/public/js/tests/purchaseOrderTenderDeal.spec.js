import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/purchasing/PurchaseOrderForm.vue"), "utf8");

/**
 * KOP-07 (docs/uat/tender/02-tender-uzmani.md:1027): `Purchase Order.custom_crm_deal`
 * is what puts a PO on the Tender PO control board (tender.py:515,538), and the
 * backend `create_purchase_order` already accepts a `deal` arg and writes it
 * (purchasing.py:1997-2004, guarded on the v34 column). But no SPA screen that
 * creates a PO ever sent it — the only writer in the whole SPA was the sourcing
 * bridge `create_po_from_quotation`. A purchaser opening a PO the normal way could
 * never attach it to its tender, and it would never appear on the control board.
 *
 * Same shape as manufacturingTabGates.spec.js: the source is EXECUTED, not
 * grepped, because a `toContain("deal")` assertion passes just as happily on a
 * gate wired backwards (e.g. sending `deal` regardless of whether `tender` is
 * even enabled for the company) as it does on a correct one.
 */
function braceMatched(from) {
	let depth = 0;
	for (let i = from; i < src.length; i++) {
		if (src[i] === "{") depth++;
		else if (src[i] === "}" && --depth === 0) return src.slice(from, i + 1);
	}
	throw new Error("unterminated block");
}

function extractFunction(name) {
	const at = src.indexOf(`function ${name}(`);
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	const braceStart = src.indexOf("{", at);
	const body = braceMatched(braceStart);
	return src.slice(at, braceStart) + body;
}

// toPayload closes over module-scope refs (`activeCompany`, `autoSubmit`) and,
// with the fix, `tenderOn` too — supply stand-ins the same way
// manufacturingTabGates.spec.js stands in for `session`/`t`.
function buildToPayload(tenderOnValue) {
	const literal = extractFunction("toPayload");
	const factory = new Function(
		"tenderOn",
		"activeCompany",
		"autoSubmit",
		`${literal}\nreturn toPayload;`
	);
	return factory({ value: tenderOnValue }, { value: "Mikas" }, { value: 1 });
}

function buildResolveDealFromQuery() {
	const literal = extractFunction("resolveDealFromQuery");
	const factory = new Function(`${literal}\nreturn resolveDealFromQuery;`);
	return factory();
}

const baseModel = () => ({
	supplier: "SUP-0001",
	set_warehouse: "",
	transaction_date: "2026-08-27",
	schedule_date: "2026-08-27",
	remarks: "",
	items: [{ item_code: "ITEM-1", qty: 1, rate: 10 }],
	currency: "",
	price_list: "",
});

describe("PurchaseOrderForm carries a tender lot to create_purchase_order (KOP-07)", () => {
	it("sends the picked deal when the tender module is on", () => {
		const toPayload = buildToPayload(true);
		const payload = toPayload({ ...baseModel(), deal: "CRM-DEAL-2026-00107" });
		expect(payload.deal).toBe("CRM-DEAL-2026-00107");
	});

	it("sends nothing when no deal was picked", () => {
		const toPayload = buildToPayload(true);
		const payload = toPayload({ ...baseModel(), deal: "" });
		expect(payload.deal).toBeUndefined();
	});

	// The invisibility requirement: even if a `deal` somehow ended up on the
	// model (stale state, a company switch mid-edit), a tenant with the tender
	// module OFF must never have it leave the browser.
	it("never sends a deal when the tender module is off, even if one is set", () => {
		const toPayload = buildToPayload(false);
		const payload = toPayload({ ...baseModel(), deal: "CRM-DEAL-2026-00107" });
		expect(payload.deal).toBeUndefined();
	});
});

describe("PurchaseOrderForm prefills ?deal= from a tender screen (module-gated)", () => {
	it("prefills the deal from the query string when tender is on", () => {
		const resolveDealFromQuery = buildResolveDealFromQuery();
		expect(resolveDealFromQuery("CRM-DEAL-2026-00107", true)).toBe("CRM-DEAL-2026-00107");
	});

	it("ignores ?deal= entirely when the tender module is off", () => {
		const resolveDealFromQuery = buildResolveDealFromQuery();
		expect(resolveDealFromQuery("CRM-DEAL-2026-00107", false)).toBe("");
	});

	it("is blank with no query param", () => {
		const resolveDealFromQuery = buildResolveDealFromQuery();
		expect(resolveDealFromQuery(undefined, true)).toBe("");
	});
});
