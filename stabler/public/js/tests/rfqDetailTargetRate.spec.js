import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/rfq/RfqDetail.vue"), "utf8");

/**
 * What unit the RFQ detail's "Target rate" column is allowed to claim.
 *
 * The bug this file exists for: `fmtRate` called `formatMoney(v, "", language)`
 * with an EMPTY currency. `money.js` has no override for "", so it reached
 * `new Intl.NumberFormat(locale, { style: "currency", currency: "" })`, which
 * throws — an empty string is not an ISO 4217 code — and the catch returned
 * `n.toFixed(2)`. Every target rate on the screen therefore printed as a bare
 * ungrouped decimal, e.g. `920000000.00`: no thousands separator, no symbol,
 * and byte-identical in English, Russian, Uzbek and Turkish. The same figure
 * renders correctly on the RFQ form, which passes a real currency.
 *
 * Why the fix is NOT "use the company's currency": the rate comes from the
 * tender intake, and the intake states its OWN currency — an import tender is
 * routinely estimated in USD while the company's books are in UZS. Labelling a
 * USD figure as UZS is a confident wrong answer, which is worse on screen than
 * an unformatted one. So the server now sends `target_currency`, and when it is
 * unknown the column says so rather than guessing.
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

/** Run `fmtRate` with the refs and the formatter it closes over injected. */
function loadFmtRate(targetCurrency, formatMoney) {
	return new Function(
		"rfq",
		"user",
		"formatMoney",
		`${extractFunction("fmtRate")}\nreturn fmtRate;`
	)({ value: { target_currency: targetCurrency } }, { value: { language: "ru" } }, formatMoney);
}

describe("the target-rate column states the unit the tender was estimated in", () => {
	it("formats with the intake's own currency, not the company's", () => {
		const formatMoney = vi.fn(() => "920 000 000,00 $");
		const fmtRate = loadFmtRate("USD", formatMoney);
		expect(fmtRate(920000000)).toBe("920 000 000,00 $");
		expect(formatMoney).toHaveBeenCalledWith(920000000, "USD", "ru");
	});

	it("refuses to render a figure whose unit nobody recorded", () => {
		// A lot captured before the intake drawer carried a currency. Grouping
		// the digits and printing them unlabelled would still be asserting they
		// are money in SOME currency the reader is left to guess.
		const formatMoney = vi.fn(() => "should not be called");
		const fmtRate = loadFmtRate("", formatMoney);
		expect(fmtRate(920000000)).toBe("—");
		expect(formatMoney).not.toHaveBeenCalled();
	});

	it("never asks the money formatter for an empty currency again", () => {
		// The regression guard. `formatMoney(v, "")` is the exact call that made
		// Intl throw into a bare toFixed, and it looks harmless at a glance.
		expect(src).not.toMatch(/formatMoney\([^)]*,\s*""/);
	});
});
