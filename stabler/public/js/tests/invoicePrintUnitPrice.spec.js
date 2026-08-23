import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/sales/InvoicePrint.vue"), "utf8");

/**
 * P0-SI-7, the printed half — a column headed "price per box" that printed the
 * price of one piece.
 *
 * The printed table already carries Rate, and Rate is per line UOM: on anjan
 * 98 160 submitted lines sell in `Korobka` (boxes), so Rate IS the box price.
 * The column beside it divided that by a piece count and called itself
 * `t("Per box")` -- "Цена за коробку" in the Russian the customer reads. A box
 * of 20 at 82 000 so'm printed 4 100 under a heading claiming it was the box.
 * 15 127 submitted invoices on anjan carry at least one such line.
 *
 * The divisor was parsed out of the item NAME, from a trailing "(N)" described
 * in the source as a reference convention. ERPNext already stores that number
 * as `conversion_factor`, and the two disagree: 9 570 anjan lines sell by the
 * box with a name ending in "(N)" while their conversion_factor is 1, and
 * another 3 760 sell by the piece -- where dividing at all understates by the
 * whole factor. The field wins over the string; it is the number ERPNext itself
 * used to post the stock movement.
 *
 * So the column states the price of ONE stock unit inside the line's UOM, and
 * says nothing when the line's UOM already IS the stock unit -- the Rate column
 * has said it. Same lifting technique as remittanceMoneyGates.spec.js: no
 * @vue/test-utils here, so the real function is executed out of the SFC.
 */
function lift(source, name) {
	const marker = `function ${name}(`;
	const start = source.indexOf(marker);
	expect(start, `InvoicePrint.vue defines no ${name}()`).toBeGreaterThan(-1);
	let depth = 0;
	let i = source.indexOf("{", start);
	const bodyStart = i;
	for (; i < source.length; i++) {
		if (source[i] === "{") depth++;
		else if (source[i] === "}" && --depth === 0) break;
	}
	const body = source.slice(bodyStart + 1, i);
	const args = source.slice(start + marker.length, source.indexOf(")", start));
	return new Function(...args.split(",").map((s) => s.trim()), body);
}

const unitPriceOf = lift(src, "unitPriceOf");

describe("unitPriceOf — the second price column on a printed invoice", () => {
	// The real anjan line: SURPRISE PRINCE shokolad (20), Korobka, cf 20,
	// 82 000 so'm a box. One piece is 4 100 -- correct number, and now under a
	// heading that says so.
	it("divides the line's rate by what ERPNext says the unit holds", () => {
		expect(unitPriceOf(82_000, 20)).toBeCloseTo(4_100, 2);
		expect(unitPriceOf(171_000, 36)).toBeCloseTo(4_750, 2);
	});

	// 3 760 anjan lines sell in Dona with cf 1: Rate is already the piece price,
	// and the old code still divided it by the "(N)" in the name -- printing a
	// twentieth or a thirty-sixth of the real figure on a customer's invoice.
	it("says nothing when the line's own UOM is already the stock unit", () => {
		expect(unitPriceOf(16_340, 1)).toBeNull();
	});

	// 9 570 anjan lines sell by the box, carry "(N)" in the name, and have
	// conversion_factor 1. The name and the field disagree; the field is the one
	// ERPNext posted the stock movement with, so it decides.
	it("trusts conversion_factor over the count written in the item name", () => {
		expect(unitPriceOf(82_000, 1)).toBeNull();
	});

	// A missing or malformed factor must not produce Infinity or NaN in a cell
	// a customer reads.
	it.each([[0], [null], [undefined], [""]])("returns null for a factor of %p", (cf) => {
		expect(unitPriceOf(82_000, cf)).toBeNull();
	});
});

describe("InvoicePrint — the column may not name a figure it does not carry", () => {
	// The heading is the actual defect: "Per box" over a per-piece number, next
	// to a Rate column that really is the box price. Asserted on the <th> rather
	// than on the whole file, because the comment above `unitPriceOf` quotes the
	// old label on purpose and a whole-file match cannot tell the two apart.
	it("no longer heads the unit-price column as the box price", () => {
		const headings = src.match(/<th[^>]*>\{\{ t\("[^"]+"\) \}\}<\/th>/g) || [];
		expect(headings.length, "the printed table has no t() headings at all").toBeGreaterThan(4);
		expect(headings.join("\n")).not.toMatch(/"Per box"/);
		expect(headings.join("\n")).toMatch(/"Unit price"/);
	});

	// The item name is not a pricing input.
	it("no longer derives a divisor from the item name", () => {
		expect(src).not.toMatch(/pcsPerBox/);
		expect(src).not.toMatch(/match\(\/\\\(\\d\+\\\)/);
	});
});
