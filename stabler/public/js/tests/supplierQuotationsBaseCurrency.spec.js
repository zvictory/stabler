import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const suppliers = readFileSync(resolve(here, "../pages/purchasing/Suppliers.vue"), "utf8");
const api = readFileSync(resolve(here, "../../../api/purchasing.py"), "utf8");

/**
 * The supplier pane's Quotations tab took the AMOUNT from `base_grand_total` and
 * the CURRENCY from `q.currency`. Those are two different denominations:
 *
 *   base_grand_total  =  the quotation converted into the COMPANY's currency
 *   currency          =  the currency the SUPPLIER quoted in
 *
 * So a Chinese supplier's bid was rendered as a so'm figure wearing a dollar
 * sign — under a column header that says "Base total". Seen on mikas
 * 2026-09-02 while checking a different report: a row printed `$182,919,065.00`
 * for a quotation whose base total is in so'm. Nobody reads that as so'm; they
 * read it as a supplier who has quoted 182 million dollars.
 *
 * The error is the exchange rate itself, so it is invisible on a single-currency
 * tenant and catastrophic on a multi-currency one — which is precisely the
 * tenant this tab was built for. It only shows up on foreign-currency
 * quotations, which is why it survived: the demo rows are all in the base.
 *
 * DOM-less per vitest.config.mjs.
 */

/** The file with every comment blanked out — line count and numbering preserved. */
function withoutComments(src) {
	const blank = (m) => m.replace(/[^\n]/g, " ");
	return src
		.replace(/<!--[\s\S]*?-->/g, blank)
		.replace(/\/\*[\s\S]*?\*\//g, blank)
		.split("\n")
		.map((line) => (/^\s*\/\//.test(line) ? "" : line))
		.join("\n");
}

/** The one formatMoney call inside the Quotations tab's table body, as its argument list. */
function baseTotalArgs() {
	const src = withoutComments(suppliers);
	const at = src.indexOf('v-for="q in suppQuotations"');
	expect(at, "the supplier Quotations table has gone").toBeGreaterThan(-1);
	const end = src.indexOf("</table>", at);
	expect(end, "the Quotations table never closes").toBeGreaterThan(at);
	const row = src.slice(at, end);
	const calls = row.match(/formatMoney\([^)]*\)/g) || [];
	// Exactly one, so a second money cell cannot appear and be silently unchecked
	// by assertions that only ever look at the first match.
	expect(calls, `expected one money cell in the row, got ${JSON.stringify(calls)}`).toHaveLength(1);
	return /formatMoney\(([^)]*)\)/
		.exec(calls[0])[1]
		.split(",")
		.map((s) => s.trim());
}

describe("the Quotations tab labels the base amount with the base currency", () => {
	it("does not pass the supplier's own currency to the base-total cell", () => {
		// WHAT WOULD MAKE THIS FAIL: `q.currency` coming back as the currency
		// argument. It is the currency the supplier QUOTED in; the amount beside it
		// has already been converted out of that currency by the server. Pairing
		// them mislabels every foreign bid by the exchange rate — not by a rounding,
		// by a factor of thousands on a UZS/USD pair — and the reader has no way to
		// tell, because the number itself is perfectly plausible.
		const [, currency] = baseTotalArgs();
		expect(currency).toBe("session.currency");
	});

	it("takes the amount from base_grand_total alone, with no transaction-currency fallback", () => {
		// WHAT WOULD MAKE THIS FAIL: `q.base_grand_total || q.grand_total`. That is
		// the same defect from the other end — when the base figure is absent or
		// zero the fallback substitutes a TRANSACTION-currency amount under a
		// base-currency label, so the row silently changes denomination while the
		// column header does not. A missing base total must render as the falsy
		// value it is, not as a different currency's number.
		//
		// `base_grand_total` is not nullable in practice (the server fetches it as a
		// Supplier Quotation field and ERPNext always computes it), so this drops no
		// data — it drops a disguise.
		const [amount] = baseTotalArgs();
		expect(amount).toBe("q.base_grand_total");
	});
});

describe("the server still supplies what the cell now assumes", () => {
	it("returns base_grand_total, so the cell has a base figure to show", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping `base_grand_total` from the fields
		// list. Having removed the `|| q.grand_total` fallback, the column would go
		// blank rather than wrong — better, but still broken, and nothing else in
		// the suite would notice.
		const fn = /def supplier_quotation_history\([\s\S]*?\n\tsqs = frappe\.get_list\(/.exec(api);
		expect(fn, "supplier_quotation_history has gone").not.toBeNull();
		expect(fn[0]).toMatch(/"base_grand_total",/);
	});

	it("scopes the query to one company, which is what makes session.currency the right base", () => {
		// WHAT WOULD MAKE THIS FAIL: removing the `company` filter. `session.currency`
		// is the SELECTED company's default currency (stores/session.js). If the rows
		// could come from several companies, one currency symbol could not be correct
		// for all of them and the fix above would be wrong in a new way. The pairing
		// is only sound because the server returns one company's rows.
		expect(api).toMatch(
			/filters=\{"supplier": supplier_name, "company": selected_company, "docstatus": \["<", 2\]\}/
		);
	});
});
