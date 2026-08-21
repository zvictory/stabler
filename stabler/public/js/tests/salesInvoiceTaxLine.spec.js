import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/sales/SalesInvoiceFormModern.vue"), "utf8");

/**
 * P0-SI-3 — the invoice screen showed a number the server did not post.
 *
 * The footer's one big figure is summed in the browser from qty × rate, so it is
 * the NET. ERPNext stores `grand_total`, which includes tax. `sales.py` has been
 * sending both `net_total` and `grand_total` all along (:1677-1678) and
 * `fromDetail` threw them away, so the screen had no way to show the posted
 * figure even in principle — and nothing on it said the two could differ.
 *
 * Measured on prod 2026-08-21 before the fix: of 20 771 invoices across anjan,
 * mikas, msa and horeca exactly ONE carried tax — but that one was off by
 * 513 971,40. So this is not a frequent lie, it is a silent one, and it becomes
 * universal the day a tenant configures a sales tax template.
 *
 * The rule has two halves, and the second is the one that is easy to get wrong:
 * show the posted total when there is tax, and do NOT show it once the user has
 * changed the amounts, because from that moment the server's figure describes a
 * document that no longer exists on screen. Replacing a stale lie with a fresher
 * lie is not a fix.
 *
 * Same constraint as remittanceMoneyGates.spec.js: @vue/test-utils is not a
 * devDependency, so the component is not mounted — the real function is lifted
 * out of the shipped SFC and executed.
 */
function liftTaxLine(source) {
	const marker = "function taxLine(";
	const start = source.indexOf(marker);
	expect(start, "SalesInvoiceFormModern.vue defines no taxLine()").toBeGreaterThan(-1);
	let depth = 0;
	let i = source.indexOf("{", start);
	const bodyStart = i;
	for (; i < source.length; i++) {
		if (source[i] === "{") depth++;
		else if (source[i] === "}" && --depth === 0) break;
	}
	expect(i, "taxLine() is not brace-balanced").toBeLessThan(source.length);
	const body = source.slice(bodyStart + 1, i);
	const signature = source.slice(start + marker.length, source.indexOf(")", start));
	return new Function(...signature.split(",").map((s) => s.trim()), body);
}

const taxLine = liftTaxLine(src);

describe("taxLine — the footer may not hide what the server will post", () => {
	// The measured normal case: 20 770 of 20 771 live invoices. Nothing extra is
	// drawn, so the screen the cashiers know does not change under them.
	it("draws nothing when the document carries no tax", () => {
		expect(taxLine(1_000_000, 1_000_000, 1_000_000)).toBeNull();
	});

	// Half a tiyin is rounding, not a tax line.
	it("treats a sub-cent difference as rounding, not tax", () => {
		expect(taxLine(1_000_000, 1_000_000.004, 1_000_000)).toBeNull();
	});

	// The real anjan invoice, at its real magnitude.
	it("reports the tax and the posted total when the screen still matches the server", () => {
		const line = taxLine(4_000_000, 4_513_971.4, 4_000_000);
		expect(line).not.toBeNull();
		expect(line.tax).toBeCloseTo(513_971.4, 2);
		expect(line.grand).toBeCloseTo(4_513_971.4, 2);
		expect(line.current).toBe(true);
	});

	// The half that matters. The user adds a line; the server's grand_total now
	// describes the document as it was BEFORE that line. Presenting it as the
	// total to be posted would be a new false figure in place of the old one.
	it("refuses to call the server's total current once the amounts have changed", () => {
		const line = taxLine(4_000_000, 4_513_971.4, 4_250_000);
		expect(line).not.toBeNull();
		expect(line.current).toBe(false);
	});

	// A brand-new invoice has no server document at all: no tax is known, so
	// there is nothing honest to add to the footer.
	it("draws nothing on a document the server has never seen", () => {
		expect(taxLine(0, 0, 250_000)).toBeNull();
		expect(taxLine(undefined, undefined, 250_000)).toBeNull();
	});
});

describe("fromDetail — the server's totals must survive the trip into the model", () => {
	// The root cause. Without these two fields in the model, taxLine() has
	// nothing to read and the footer is structurally unable to tell the truth.
	it("keeps net_total and grand_total", () => {
		const start = src.indexOf("function fromDetail(");
		const end = src.indexOf("\n}", start);
		const body = src.slice(start, end);
		expect(body).toMatch(/net_total:/);
		expect(body).toMatch(/grand_total:/);
	});
});
