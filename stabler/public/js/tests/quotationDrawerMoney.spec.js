import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../components/QuotationEntryDrawer.vue"), "utf8");

/**
 * How the quotation drawer renders money, and how it says it is busy.
 *
 * This drawer is the reference the other screens are told to copy, which is
 * exactly why these two slips matter more here than anywhere else.
 *
 * Money: the line total and the grand total were rendered with a bare
 * `Number.prototype.toLocaleString()`. That formats in the BROWSER's default
 * locale, not the user's chosen language, and it knows nothing about the house
 * rule for how many fraction digits a currency carries — so the one screen
 * where a supplier's price is typed could disagree, visibly, with every other
 * money value in the product. The grand total then had the currency code
 * concatenated after it by hand, which is the shared formatter's job.
 *
 * The currency here can genuinely be EMPTY: `form.currency` starts as
 * `currency.value || ""` and is only filled if the currency list loaded. So the
 * fix cannot simply pass it through — `formatMoney(v, "")` makes Intl throw and
 * falls back to an unformatted `toFixed(2)`, the same trap the RFQ detail's
 * target-rate column was sitting in. An amount whose unit is unknown is not
 * measurable, and says so.
 *
 * Busy: both buttons already swap their label, which is the mandated pattern.
 * Neither told assistive technology anything, so the sighted half of the
 * signal existed and the non-visual half did not.
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

function loadFmtAmount(formCurrency, formatMoney) {
	return new Function(
		"form",
		"user",
		"formatMoney",
		`${extractFunction("fmtAmount")}\nreturn fmtAmount;`
	)({ value: { currency: formCurrency } }, { value: { language: "ru" } }, formatMoney);
}

describe("the quotation drawer prices lines through the house formatter", () => {
	it("formats with the quotation's own currency and the user's language", () => {
		// A quotation is entered in the SUPPLIER's currency, which is the whole
		// reason the drawer carries a currency picker at all.
		const formatMoney = vi.fn(() => "1 200,00 $");
		expect(loadFmtAmount("USD", formatMoney)(1200)).toBe("1 200,00 $");
		expect(formatMoney).toHaveBeenCalledWith(1200, "USD", "ru");
	});

	it("refuses to price an amount before a currency is known", () => {
		// The currency list request can fail, and the field then stays empty.
		// Printing a bare grouped number here would assert it is money in some
		// unit the reader has to guess — and passing "" to the formatter is the
		// exact call that silently degrades into an unformatted toFixed.
		const formatMoney = vi.fn(() => "should not be called");
		expect(loadFmtAmount("", formatMoney)(1200)).toBe("—");
		expect(formatMoney).not.toHaveBeenCalled();
	});

	it("no longer formats any money with the browser's own locale", () => {
		// The regression guard. It reads as harmless and is the single easiest
		// way to reintroduce this whole class of bug. Anchored on the dot: the
		// defect is always a method call on a value, so prose about it in a
		// comment is not a match and the explanation can stay in the source.
		expect(src).not.toMatch(/\.toLocaleString\(/);
	});

	it("stopped pasting the currency code on after the number", () => {
		// The formatter owns the symbol and its placement; a hand-appended code
		// is how "1 200,00 $ USD" happens.
		expect(src).not.toMatch(/\}\}\s*\{\{\s*form\.currency\s*\}\}/);
	});
});

describe("the drawer says it is busy to more than the eye", () => {
	it("binds aria-busy on both the save and the submit button", () => {
		// The labels already swap. Without this the announcement exists only for
		// users who can see it — half a signal, on the drawer every other screen
		// is told to copy.
		expect(src).toMatch(/:aria-busy="saving"/);
		expect(src).toMatch(/:aria-busy="submitting"/);
	});

	it("keeps the label swap that the aria state describes", () => {
		// aria-busy without the visible swap would be the mirror-image bug.
		expect(src).toMatch(/saving \? t\("Saving…"\) : t\("Save draft"\)/);
		expect(src).toMatch(/submitting \? t\("Submitting…"\) : t\("Submit quotation"\)/);
	});
});

describe("the line table scrolls inside itself", () => {
	it("wraps the five-column table so a narrow drawer never pushes sideways", () => {
		// The package rule is absolute: wide content scrolls in its own
		// container, the page body never scrolls horizontally.
		const at = src.indexOf('<table class="ds-table qed-lines">');
		expect(at, "the line table is gone — has it been renamed?").toBeGreaterThan(-1);
		expect(src.slice(Math.max(0, at - 200), at)).toMatch(/table-responsive/);
	});
});
