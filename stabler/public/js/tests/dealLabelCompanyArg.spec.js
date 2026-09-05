import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const poSrc = readFileSync(resolve(here, "../pages/purchasing/PurchaseOrderForm.vue"), "utf8");
const expensesSrc = readFileSync(resolve(here, "../pages/money/Expenses.vue"), "utf8");

/**
 * Measured 2026-09-05 in the browser on the local `stabler` site:
 * `stabler.api.crm.get_deal` (crm.py:486) calls `_require_crm_company` ->
 * `_require_company` (_common.py:14), which throws "Company is required."
 * when `company` is empty. Both `loadDealLabel` call sites here called
 * `get_deal` with only `{ name }`, so the server always rejected the read --
 * the `catch` block then silently fell back to the raw deal id
 * ("CRM-DEAL-2026-00015") instead of showing the resolved organization. The
 * fix threads `company: activeCompany.value` through, matching the
 * already-working callers `searchDeals` (this file), `Deals.vue:501` and
 * `Deal360View.vue:35-38`.
 *
 * Same shape as purchaseOrderTenderDeal.spec.js: the source is EXECUTED, not
 * grepped. A stub `call` that enforces the server's actual gate proves the
 * label resolves end-to-end; a bare `toContain("company")` would pass just as
 * happily on a call that sends `company` under the wrong key or to the wrong
 * method.
 */
function braceMatched(src, from) {
	let depth = 0;
	for (let i = from; i < src.length; i++) {
		if (src[i] === "{") depth++;
		else if (src[i] === "}" && --depth === 0) return src.slice(from, i + 1);
	}
	throw new Error("unterminated block");
}

function extractFunction(src, name) {
	// `async function NAME(` first -- see purchaseOrderTenderDeal.spec.js for
	// why a plain `indexOf("function NAME(")` would silently drop "async".
	let at = src.indexOf(`async function ${name}(`);
	if (at === -1) at = src.indexOf(`function ${name}(`);
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	const braceStart = src.indexOf("{", at);
	const body = braceMatched(src, braceStart);
	return src.slice(at, braceStart) + body;
}

// The server's actual gate (_common.py:14: `if not company: frappe.throw(...)`),
// not a loose stand-in -- so this fails the exact way the real endpoint does
// when a call site forgets `company`, and resolves the exact shape `get_deal`
// returns when it doesn't (organization present, lead_name null, per the
// Mikas/CRM-DEAL-2026-00015 read in the bug report).
function serverStubCall(_method, args) {
	if (!args.company) throw new Error("Company is required.");
	return {
		name: args.name,
		organization: "O'zbekiston temir yo'llari AJ [DEMO]",
		lead_name: null,
	};
}

describe("PurchaseOrderForm.loadDealLabel sends company to get_deal (measured 2026-09-05)", () => {
	it("resolves 'org · id' instead of falling back to the raw deal id, because the server rejects a company-less read", async () => {
		const dealOptionLabelLiteral = extractFunction(poSrc, "dealOptionLabel");
		const loadDealLabelLiteral = extractFunction(poSrc, "loadDealLabel");
		const factory = new Function(
			"call",
			"dealLabel",
			"activeCompany",
			`${dealOptionLabelLiteral}\n${loadDealLabelLiteral}\nreturn loadDealLabel;`
		);
		const dealLabel = { value: "" };
		const activeCompany = { value: "Mikas" };
		const loadDealLabel = factory(serverStubCall, dealLabel, activeCompany);

		await loadDealLabel("CRM-DEAL-2026-00015");

		// Pre-fix this reads "CRM-DEAL-2026-00015" -- the catch block's raw-id
		// fallback -- because the stub above throws "Company is required." when
		// `company` is missing from the get_deal args.
		expect(dealLabel.value).toBe("O'zbekiston temir yo'llari AJ [DEMO] · CRM-DEAL-2026-00015");
	});

	it("passes company on the get_deal call, so a future edit that drops it fails loudly", () => {
		const loadDealLabelLiteral = extractFunction(poSrc, "loadDealLabel");
		expect(loadDealLabelLiteral).toMatch(/get_deal["'],\s*\{[^}]*\bcompany\s*:/);
	});
});

describe("Expenses.loadDealLabel sends company to get_deal (measured 2026-09-05)", () => {
	it("resolves the organization instead of falling back to the raw deal id, because the server rejects a company-less read", async () => {
		const loadDealLabelLiteral = extractFunction(expensesSrc, "loadDealLabel");
		const factory = new Function(
			"call",
			"dealLabel",
			"activeCompany",
			`${loadDealLabelLiteral}\nreturn loadDealLabel;`
		);
		const dealLabel = { value: "" };
		const activeCompany = { value: "Mikas" };
		const loadDealLabel = factory(serverStubCall, dealLabel, activeCompany);

		await loadDealLabel("CRM-DEAL-2026-00015");

		// Pre-fix this reads "CRM-DEAL-2026-00015" for the same reason as the PO
		// form above: the stub throws before organization is ever returned, and
		// the fallback silently shows the raw id instead.
		expect(dealLabel.value).toBe("O'zbekiston temir yo'llari AJ [DEMO]");
	});

	it("passes company on the get_deal call, so a future edit that drops it fails loudly", () => {
		const loadDealLabelLiteral = extractFunction(expensesSrc, "loadDealLabel");
		expect(loadDealLabelLiteral).toMatch(/get_deal["'],\s*\{[^}]*\bcompany\s*:/);
	});
});
