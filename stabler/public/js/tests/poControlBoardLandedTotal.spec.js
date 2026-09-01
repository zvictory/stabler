import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/PoControlBoard.vue"), "utf8");

/**
 * What the landed-charge editor's footer is allowed to add up.
 *
 * The bug this file exists for: a charge line quoted in a foreign currency
 * carries the user's figure in `amount_original`. The company-currency `amount`
 * is derived by the SERVER, at the one chokepoint both reads and writes pass
 * through (`stabler/api/tender.py`, "what stops the two from ever disagreeing").
 * So while the modal is open `amount` is null on a line just added and stale on
 * one just edited — and the footer summed exactly that field.
 *
 * The result was arithmetic the user could watch go wrong: a 1 200 USD freight
 * line printed `= 15 360 000` in its own cell, from `convertedPreview`, and
 * contributed ZERO to the "Landed total" printed directly beneath it. The stored
 * plan was correct the whole time — `saveEditor` sends `amount_original` and the
 * server re-derives — so this was never data corruption. It was worse placed
 * than that: right in the database, wrong on the screen where the vendor is
 * chosen.
 *
 * `null` from a preview means the line cannot be valued at all (a currency with
 * no usable rate). Those must be COUNTED, never silently added as zero — adding
 * them as zero is how a total quietly shrinks, which is the failure the module's
 * own comment names.
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

const load = (name) => new Function(`${extractFunction(name)}\nreturn ${name};`)();

const convertedPreview = load("convertedPreview");
const actualPreview = load("actualPreview");
const priceLines = load("priceLines");

/** 1 200 USD at 12 800 — the line the officer just added, not yet saved. */
const FRESH_FOREIGN = { currency: "USD", fx_rate: 12800, amount_original: 1200, amount: null, actual: null, actual_original: null };
/** The same line after the server has valued it, then re-typed by the user. */
const EDITED_FOREIGN = { currency: "USD", fx_rate: 12800, amount_original: 2000, amount: 12800000, actual: null, actual_original: null };
/** Currency chosen, no rate yet: not valuable, and not zero either. */
const UNVALUED = { currency: "USD", fx_rate: 0, amount_original: 1200, amount: null, actual: null, actual_original: null };
/** An ordinary company-currency line. */
const HOME = { currency: "", fx_rate: 0, amount_original: null, amount: 3200000, actual: 3100000, actual_original: null };

describe("the landed-charge footer counts what the rows are showing", () => {
	it("counts a freshly added foreign line at the figure its own cell prints", () => {
		// The regression, stated as arithmetic: the cell renders convertedPreview
		// and the footer must reach the same number. Summing `amount` gives 0 here.
		expect(convertedPreview(FRESH_FOREIGN)).toBe(15360000);
		expect(priceLines([FRESH_FOREIGN], convertedPreview).total).toBe(15360000);
	});

	it("follows the user's edit rather than the server's stale conversion", () => {
		// `amount` still holds the value of the PREVIOUS figure. Believing it
		// would price the plan at what the officer typed a minute ago.
		expect(priceLines([EDITED_FOREIGN], convertedPreview).total).toBe(25600000);
	});

	it("counts a line it cannot value instead of adding it as zero", () => {
		const { total, unvalued } = priceLines([HOME, UNVALUED], convertedPreview);
		expect(total).toBe(3200000);
		expect(unvalued).toBe(1);
	});

	it("still reads company-currency lines from the derived field", () => {
		// A line with no currency of its own has nothing to convert; `amount` is
		// the figure, and the customs calculator writes it directly.
		expect(priceLines([HOME], convertedPreview).total).toBe(3200000);
		expect(priceLines([HOME], convertedPreview).unvalued).toBe(0);
	});

	it("treats an actual nobody has recorded yet as zero, not as unmeasurable", () => {
		// Planned and actual are not symmetrical. A planned line with a currency
		// and no rate is an INCOMPLETE PLAN and must be flagged. An actual of
		// nothing is not incomplete — it is the ordinary state of a charge that
		// has not been invoiced yet, and flagging it would put a permanent
		// warning under every open PO.
		expect(actualPreview(FRESH_FOREIGN)).toBe(0);
		expect(priceLines([FRESH_FOREIGN], actualPreview).unvalued).toBe(0);
	});

	it("cannot value an actual that was recorded in a currency with no rate", () => {
		const recorded = { ...UNVALUED, actual_original: 900 };
		expect(actualPreview(recorded)).toBeNull();
		expect(priceLines([recorded], actualPreview).unvalued).toBe(1);
	});
});

describe("the footer's totals are wired to those functions, not to the derived fields", () => {
	it("neither total reduces over the server-derived amount/actual", () => {
		// The guard on the wiring. The arithmetic above can be perfect while the
		// computeds still sum `l.amount` — that is exactly the shape the bug had.
		expect(src).not.toMatch(/reduce\(\(a, l\) => a \+ \(Number\(l\.amount\) \|\| 0\), 0\)/);
		expect(src).not.toMatch(/reduce\(\(a, l\) => a \+ \(Number\(l\.actual\) \|\| 0\), 0\)/);
		expect(src).toMatch(/priceLines\(editorLines\.value, convertedPreview\)/);
		expect(src).toMatch(/priceLines\(editorLines\.value, actualPreview\)/);
	});

	it("tells the user what the total left out, on both halves of the footer", () => {
		// A total that is merely CORRECT about what it could value, while silently
		// dropping what it could not, is the same lie in a quieter voice. Both
		// halves must surface the count, and severity here is carried by three
		// codes at once — colour, icon and word — not by colour alone.
		const warnings = src.match(/v-if="editor(Planned|ActualPriced)\.unvalued"/g) || [];
		expect(warnings).toHaveLength(2);
		expect(src).toMatch(/Lines with no exchange rate, not in this total: \{count\}/);
	});
});
