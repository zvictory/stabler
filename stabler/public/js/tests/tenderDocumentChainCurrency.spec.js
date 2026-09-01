import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/TenderDocumentChain.vue"), "utf8");

/**
 * Which currency each row of the execution chain is printed in.
 *
 * The bug this file exists for: the chain took ONE `currency` prop —
 * `PoControlBoard.vue` passes it the tender's company currency — and printed
 * every row with it. Both chains. The server has always sent a per-row
 * `currency` beside `grand_total` (`stabler/api/tender.py`, `_document_row`),
 * read from each ERPNext document's own field, and the chain never looked at it.
 *
 * A tender is exactly where this bites. The purchase side is a PO to a foreign
 * supplier in USD; the sales side is an order to a state buyer invoiced in UZS.
 * Same screen, same column, and the amount was rendered in a unit it was not
 * written in — the figure right, the label wrong, which is the worst of the two
 * halves to get wrong because nothing about it looks broken.
 *
 * The board itself already had the answer one component away:
 * `PoControlBoard.vue` prints its charge lines with `c.currency || ccy`.
 *
 * Not `base_grand_total`: the server sends that too, and converting everything
 * to the company currency would make a column of numbers comparable. But this
 * screen sums nothing — it is a list of documents someone is looking up, not a
 * total — and restating a supplier's USD invoice as a UZS figure would answer a
 * question nobody asked while losing the one the reader came for.
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
	return src.slice(at, braceStart) + braceMatched(braceStart);
}

const loadRowCurrency = (tenderCurrency) =>
	new Function("props", `${extractFunction("rowCurrency")}\nreturn rowCurrency;`)({
		currency: tenderCurrency,
	});

describe("each document in the chain is priced in the currency it was written in", () => {
	it("uses the row's own currency over the tender's", () => {
		// The purchase order to the foreign supplier.
		expect(loadRowCurrency("UZS")({ currency: "USD", grand_total: 152000 })).toBe("USD");
	});

	it("falls back to the tender's currency when a row states none", () => {
		// Older rows, and documents whose currency field is genuinely empty.
		// Falling back is what the board's own charge lines already do.
		expect(loadRowCurrency("UZS")({ currency: "", grand_total: 152000 })).toBe("UZS");
	});

	it("no longer prints every row with the single prop", () => {
		// The regression guard: the template must reach the row's currency, and
		// `formatMoney(row.grand_total, currency, …)` is what it used to do.
		expect(src).not.toMatch(/formatMoney\(row\.grand_total,\s*currency\s*,/);
		expect(src).toMatch(/formatMoney\(row\.grand_total,\s*rowCurrency\(row\)\s*,/);
	});
});
