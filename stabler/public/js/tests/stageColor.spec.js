import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { contrastRatio, parseColor, stageTone, tintOver } from "../composables/color.js";

const here = dirname(fileURLToPath(import.meta.url));
const board = readFileSync(resolve(here, "../pages/sales/SalesOrderBoard.vue"), "utf8");
const api = readFileSync(resolve(here, "../../../api/tender.py"), "utf8");

/**
 * A stage colour is user data, and the board printed it raw — prompt 18's S3,
 * acceptance row C19.
 *
 *     :style="{ background: colorOf(s) + '22',
 *               color: colorOf(s),
 *               border: `1px solid ${colorOf(s)}55` }"
 *
 * Two defects in three lines. `+ '22'` produces a valid 8-digit hex ONLY if the
 * stored value is exactly six digits with a leading `#` — the field is a plain
 * `Data`, so a 3-digit hex, an 8-digit one, or a CSS colour name silently
 * yields an invalid declaration and the badge loses its tint. And the count is
 * printed in the stage's own colour on a 13 % tint of itself, which nothing
 * checks.
 *
 * Measured 2026-09-02, and the measurement is the reason this file exists: NOT
 * ONE of the seven seeded stage colours clears WCAG AA (4.5:1) as its own text
 * on its own tint. The best is Delivery at 4.18; *Closed* is 1.91 and
 * *Procurement* 1.93. S3 called `#adb5bd` "already marginal" — every column was
 * over the line, not just that one.
 *
 * So the rule is not "use the colour unless it is bad". The colour is DARKENED
 * until it passes, which keeps the hue (all three channels scale by the same
 * factor, so the ratios between them are exact) and costs one to five steps on
 * the seeded palette. Replacing it with a fixed ink would have been fewer lines
 * and would have thrown the hue away on all seven columns at once.
 */

/** The seven stages a fresh site is seeded with, read from the server source. */
function seededColours() {
	const block = api.match(/_DEFAULT_STAGES = \[([\s\S]*?)\n\]/);
	expect(block, "_DEFAULT_STAGES has moved").not.toBeNull();
	const rows = [...block[1].matchAll(/\("([^"]+)", \d+, "([^"]+)"/g)].map((m) => [m[1], m[2]]);
	expect(rows.length, "no seeded stages parsed").toBeGreaterThan(0);
	return rows;
}

/** The rgb triple inside an `rgb(...)`/`rgba(...)` string. */
function channels(css) {
	const m = css.match(/rgba?\((\d+), (\d+), (\d+)/);
	expect(m, `not an rgb() string: ${css}`).not.toBeNull();
	return m.slice(1, 4).map(Number);
}

describe("parseColor accepts what the field can actually hold", () => {
	it("reads the six-digit hex the palette is written in", () => {
		// WHAT WOULD MAKE THIS FAIL: the ordinary case breaking. Every seeded
		// stage is a six-digit hex, so this is the path the board is on today.
		expect(parseColor("#6c757d")).toEqual([108, 117, 125]);
		expect(parseColor("#FFFFFF")).toEqual([255, 255, 255]);
	});

	it("reads the shorthand too, which the old string concatenation broke", () => {
		// WHAT WOULD MAKE THIS FAIL: assuming six digits. `"#f90" + "22"` is
		// `"#f9022"` — five digits, not a colour at all — so the badge lost its
		// background entirely and nothing said why. The field is a plain `Data`
		// column: nothing stops a manager storing the shorthand.
		expect(parseColor("#f90")).toEqual([255, 153, 0]);
	});

	it("ignores an alpha the value already carries", () => {
		// WHAT WOULD MAKE THIS FAIL: appending a second alpha to an 8-digit hex.
		// `"#6c757dff" + "22"` is ten digits; the tint is this screen's to decide
		// and a stored alpha is not a stage's opinion about it.
		expect(parseColor("#6c757dff")).toEqual([108, 117, 125]);
	});

	it("returns nothing for a value it cannot read", () => {
		// WHAT WOULD MAKE THIS FAIL: guessing. A CSS colour name is legal in the
		// `color:` line and illegal in the concatenated one, so the old code half
		// worked and produced a badge with a broken background — the worst of the
		// three outcomes. Refusing it is what lets stageTone fall back whole.
		for (const bad of ["red", "", null, undefined, "#12", "not a colour", "#gggggg"]) {
			expect(parseColor(bad), `parseColor(${JSON.stringify(bad)})`).toBeNull();
		}
	});
});

describe("the tint and the border are real colours", () => {
	it("emits rgba() rather than concatenating an alpha onto a hex", () => {
		// WHAT WOULD MAKE THIS FAIL: `+ '22'` coming back. Producing the alpha
		// arithmetically is what makes every input above work — the shorthand,
		// the 8-digit form, and the fallback — instead of only the one shape the
		// seeded palette happens to use.
		const tone = stageTone("#f90");
		expect(tone.tint).toMatch(/^rgba\(255, 153, 0, 0\.13\)$/);
		expect(tone.border).toMatch(/^rgba\(255, 153, 0, 0\.33\)$/);
		expect(tone.line).toBe("rgb(255, 153, 0)");
	});

	it("falls back whole rather than in pieces", () => {
		// WHAT WOULD MAKE THIS FAIL: falling back for the tint and keeping the
		// raw value for the text. That is exactly the old behaviour for a CSS
		// colour name — a coloured number on a background that failed to render
		// — and it is worse than either being wrong consistently.
		const bad = stageTone("papayawhip");
		const none = stageTone("");
		expect(bad).toEqual(none);
		expect(channels(bad.line)).toEqual(parseColor("#6c757d"));
	});
});

describe("no stage colour can make its own count unreadable", () => {
	it("clears WCAG AA on every seeded stage", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping the contrast step. This is the
		// measurement that decided the design: not one of these seven passed
		// before, so a rule of the form "use the colour unless it is bad" would
		// have left the board exactly as it was.
		for (const [name, hex] of seededColours()) {
			const tone = stageTone(hex);
			const ratio = contrastRatio(channels(tone.text), tintOver(parseColor(hex), 0.13));
			expect(ratio, `${name} (${hex}) reads at ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
		}
	});

	it("clears it for a pale colour a manager could pick tomorrow", () => {
		// WHAT WOULD MAKE THIS FAIL: a rule tuned to the seeded palette. The
		// field is free-form; pale yellow is the case S3 named, and near-white is
		// the one that makes a naive loop run forever.
		for (const hex of ["#ffe066", "#fffef8", "#ffffff"]) {
			const tone = stageTone(hex);
			const ratio = contrastRatio(channels(tone.text), tintOver(parseColor(hex), 0.13));
			expect(ratio, `${hex} reads at ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
		}
	});

	it("keeps the hue while it darkens", () => {
		// WHAT WOULD MAKE THIS FAIL: substituting a fixed ink, or shifting the
		// channels unevenly. The colour is the only thing telling the reader
		// which column they are looking at without reading its name; darkening
		// scales all three channels by ONE factor, so the ratios between them
		// survive exactly and orange stays orange.
		const orange = parseColor("#f59f00");
		const out = channels(stageTone("#f59f00").text);
		expect(out[0]).toBeGreaterThan(out[1]);
		expect(out[1]).toBeGreaterThan(out[2]);
		const factor = out[0] / orange[0];
		expect(out[1] / orange[1]).toBeCloseTo(factor, 1);
	});

	it("leaves a colour alone when it already reads", () => {
		// WHAT WOULD MAKE THIS FAIL: darkening unconditionally. A stage set to a
		// dark colour is already legible; changing it anyway would mean the badge
		// never shows the colour the manager actually chose.
		expect(stageTone("#333333").text).toBe("rgb(51, 51, 51)");
	});
});

describe("the board uses it", () => {
	it("stops concatenating alpha onto the stage colour", () => {
		// WHAT WOULD MAKE THIS FAIL: the helper landing and the template still
		// building its own colours — the fix present, wired to nothing, and every
		// test above still green because they call the helper directly.
		//
		// Anchored to the SHAPE, not to the old variable's name: the first
		// version of this matched `colorOf(s) + '22'`, and `colorOf` no longer
		// exists — so renaming the variable while keeping the concatenation
		// walked straight past it. Found by mutating the template and getting
		// only one red instead of two.
		expect(/\+\s*["'][0-9a-f]{2}["']/i.test(board), "a two-digit alpha is concatenated again").toBe(
			false
		);
		expect(/\}[0-9a-f]{2}`/i.test(board), "a two-digit alpha is appended in a template literal").toBe(
			false
		);
	});

	it("draws the header from the helper's three colours", () => {
		expect(board).toMatch(/import \{[^}]*\bstageTone\b[^}]*\} from "\.\.\/\.\.\/composables\/color\.js"/);
		expect(board).toMatch(/toneOf\(s\)\.tint/);
		expect(board).toMatch(/toneOf\(s\)\.text/);
		expect(board).toMatch(/toneOf\(s\)\.border/);
		expect(board).toMatch(/toneOf\(s\)\.line/);
	});
});
