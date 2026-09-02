import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "fs";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const jsRoot = resolve(here, "..");
const EDITOR = readFileSync(resolve(jsRoot, "components/LineItemsEditor.vue"), "utf8");
const RETURN_FORM = readFileSync(resolve(jsRoot, "pages/sales/SalesReturnForm.vue"), "utf8");

/**
 * The direct sales return must not offer a button that cannot work.
 *
 * `_normalize_direct_return_items` (api/sales.py) refuses `rate <= 0`. The shared
 * grid only refused a NEGATIVE rate, so a line at 0.00 was "valid", the
 * validity-change emit stayed true, and "Create credit note" stayed enabled. The
 * operator pressed it and the request died at the backend guard — which, until the
 * same change, was mute: HTTP 417 and no text. Measured on anjan 2026-09-02.
 *
 * The gate is OPT-IN and the shared default stays permissive, because seven of the
 * eight callers of LineItemsEditor legitimately allow a zero rate:
 *
 *   QuotationForm · SalesOrderFormClassic · SalesOrderFormModern · SalesOrderLines
 *   PurchaseInvoiceForm · PurchaseOrderForm · TenderMasterDrawer
 *
 * Every one of them saves a DRAFT first and submits as a separate act, so a rate
 * that is not known yet is a legitimate state of the document; their backends set
 * no positive-rate condition either (free samples, bonus goods, zero-value
 * replacement lines). SalesReturnForm is the only one-shot submit —
 * `create_direct_sales_return` ends in insert() + submit() — so there a zero rate is
 * unsubmittable at the moment the button is pressed, and only there must the form
 * say so before the request goes out.
 *
 * Source-reading, not mounting: `vitest.config.mjs` sets `environment: "node"` and
 * `@vue/test-utils` is not a dependency, so a structural contract is what can be
 * pinned here.
 */

function getLineErrorsBody() {
	const start = EDITOR.indexOf("function getLineErrors(");
	expect(start, "getLineErrors() has been renamed or removed").toBeGreaterThan(-1);
	return EDITOR.slice(start, EDITOR.indexOf("\n}", start));
}

function vueFilesUnder(dir) {
	const out = [];
	for (const entry of readdirSync(dir)) {
		const full = join(dir, entry);
		if (statSync(full).isDirectory()) out.push(...vueFilesUnder(full));
		else if (entry.endsWith(".vue")) out.push(full);
	}
	return out;
}

describe("sales return — the zero-rate gate", () => {
	it("declares requirePositiveRate and leaves the shared default permissive", () => {
		expect(EDITOR).toMatch(/requirePositiveRate:\s*\{\s*type:\s*Boolean,\s*default:\s*false\s*\}/);
	});

	it("gates the positive-rate rule on the prop, keeping the negative check", () => {
		const body = getLineErrorsBody();
		expect(body).toMatch(/Number\(line\.rate\)\s*<\s*0/);
		expect(body).toMatch(/props\.requirePositiveRate/);
		expect(body.replace(/\s+/g, " ")).toMatch(
			/else if \(props\.requirePositiveRate && !\(Number\(line\.rate\) > 0\)\)/
		);
	});

	it("is opted into by the return screen", () => {
		expect(RETURN_FORM).toMatch(/require-positive-rate/);
	});

	it("is opted into by NOTHING else", () => {
		const optedIn = vueFilesUnder(jsRoot)
			.filter((p) => readFileSync(p, "utf8").includes("require-positive-rate"))
			.map((p) => p.split("/").pop())
			.sort();
		expect(
			optedIn,
			"the other seven callers save a draft first, where a zero rate is legitimate"
		).toEqual(["SalesReturnForm.vue"]);
	});

	it("still disables the submit button on an invalid grid", () => {
		expect(RETURN_FORM).toMatch(/:disabled="actionRunning \|\| !isFormValidState"/);
	});
});

describe("sales return — a failed price lookup is not swallowed", () => {
	function pickItemBody() {
		const start = RETURN_FORM.indexOf("async function pickItem(");
		expect(start, "pickItem() has been renamed or removed").toBeGreaterThan(-1);
		return RETURN_FORM.slice(start, RETURN_FORM.indexOf("\n}", start));
	}

	it("binds the error instead of discarding it", () => {
		// `catch {` threw the only evidence away: item_sales_meta returns 630.0 USD
		// for the very item that landed on the screen at 0.00, and nobody could see
		// why the browser call disagreed.
		expect(pickItemBody()).toMatch(/catch\s*\(\s*\w+\s*\)\s*\{/);
	});

	it("reports the failure to the console for the next occurrence", () => {
		expect(pickItemBody()).toMatch(/console\.error\(/);
	});

	it("tells the user the rate has to be typed by hand", () => {
		expect(pickItemBody()).toMatch(/toast\./);
		expect(RETURN_FORM).toMatch(/useToast/);
	});

	it("warns when the lookup succeeds but resolves no usable price", () => {
		// item_sales_meta can also return price_list_rate 0 with unresolved: true —
		// no exception is thrown, so the catch never runs and the row still lands at 0.
		expect(pickItemBody().replace(/\s+/g, " ")).toMatch(/if \(!\(Number\(line\.rate\) > 0\)\)/);
	});
});
