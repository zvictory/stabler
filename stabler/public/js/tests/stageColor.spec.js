import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import {
	contrastRatio,
	nextStageColor,
	parseColor,
	stageTone,
	tintOver,
} from "../composables/color.js";

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
		//
		// The second assertion used to read `channels(bad.line) === parseColor("#6c757d")`
		// — it pinned the fallback to *New*'s own colour, which is the defect S3
		// reported. Corrected rather than deleted: the claim it was making (the
		// fallback is one whole tone, not a mix) is still the right claim.
		const bad = stageTone("papayawhip");
		const none = stageTone("");
		expect(bad).toEqual(none);
		expect(bad.line, "the fallback claims a colour again").not.toMatch(/rgb/);
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


/**
 * ── S3 problem 1 ────────────────────────────────────────────────────────────
 *
 * The fallback above was the literal `#6c757d`, which is ALSO the *New* stage's
 * own colour, so a stage with no colour rendered as a second *New*. That was not
 * a rare edge: `so_stage_save` has always accepted a `color` argument and the
 * board never sent one, so EVERY stage a manager created through the board came
 * out uncoloured.
 *
 * Measured 2026-09-02, and the measurement changed the fix. Swapping the neutral
 * for a different grey does nothing — the badge is a 13 % tint over white, and
 * every grey in the house palette lands within 1.11:1 of *New*'s badge, i.e.
 * indistinguishable. So an uncoloured stage is rendered as UNCOLOURED rather
 * than as a different colour, and the real repair is upstream: new stages are
 * born with one.
 *
 * The colour is GENERATED, not taken from a list. Also measured that day: of the
 * ten colours in the CRM's own kanban palette, nine sit within 18° of a seeded
 * stage's hue (`cyan` is 4° from *Invoicing*, `gray` 0° from *New*) while the
 * seeded seven's own tightest chromatic gap is 40°. A fixed list cannot beat
 * that; putting each new stage in the middle of the widest unused arc can, and
 * keeps working after stages are deleted or recoloured.
 */

/** Hue in degrees, computed here rather than imported — a test that shares the
 *  implementation's own arithmetic cannot detect an error in it. */
function hueOf(hex) {
	const [r, g, b] = parseColor(hex).map((v) => v / 255);
	const mx = Math.max(r, g, b);
	const d = mx - Math.min(r, g, b);
	if (!d) return null; // grey: no hue at all
	const h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
	return (h * 60 + 360) % 360;
}

/** The smaller of the two ways round the colour wheel, 0 … 180. */
function hueGap(a, b) {
	const d = Math.abs(a - b) % 360;
	return d > 180 ? 360 - d : d;
}

describe("a stage with no colour does not impersonate *New*", () => {
	it("no longer carries *New*'s hex as its fallback", () => {
		// WHAT WOULD MAKE THIS FAIL: `#6c757d` coming back as the neutral. This is
		// S3's report in one line — the fallback WAS the New stage's colour, so the
		// board drew two columns the same and neither was labelled as the default.
		//
		// Comments stripped first: the module explains which colour it stopped
		// using, and banning the string rather than the value would forbid it from
		// saying so. Same correction the `window.prompt` guard needed.
		const code = readFileSync(resolve(here, "../composables/color.js"), "utf8")
			.replace(/\/\*[\s\S]*?\*\//g, "")
			.replace(/\/\/[^\n]*/g, "");
		expect(/6c757d/i.test(code), "color.js still hardcodes *New*'s own colour").toBe(false);
		expect(/108,\s*117,\s*125/.test(code), "*New*'s colour is back as a decimal triple").toBe(false);

		// And the same claim behaviourally, because the two above are spellings and
		// there are more of them. The original defect was written `[108, 117, 125]`
		// with the hex in a COMMENT — so a source ban that strips comments, as this
		// one must, would not have caught the very code it exists to prevent.
		const none = stageTone("");
		const asNew = stageTone("#6c757d");
		for (const key of ["line", "tint", "border", "text"]) {
			expect(none[key], `an uncoloured stage renders *New*'s ${key}`).not.toBe(asNew[key]);
		}
	});

	it("renders no tint at all rather than a different grey", () => {
		// WHAT WOULD MAKE THIS FAIL: substituting another neutral. The next test
		// records why that would not have worked; this one pins the decision that
		// followed from it. A stage with no colour looks like a stage with no
		// colour — the badge takes the page's own background, not a fill that
		// claims a colour nobody chose.
		const none = stageTone("");
		expect(none.tint).toBe("transparent");
		expect(none.text).not.toMatch(/rgb/);
		expect(none.line, "the column head loses its rule entirely").not.toBe("");
		expect(none.border, "the badge loses its outline entirely").not.toBe("");
	});

	it("records the measurement that ruled out simply changing the grey", () => {
		// WHAT WOULD MAKE THIS FAIL: nothing in the source — this is arithmetic on
		// the house palette, kept because it is the reason the fix is shaped the way
		// it is. Someone reading "why not just pick another grey?" gets a number.
		//
		// 1.00 is "identical". Anything under about 1.2 is two fills nobody can tell
		// apart at badge size, which is what all three candidates are.
		const newBadge = tintOver(parseColor("#6c757d"), 0.13);
		for (const grey of ["#8b95a5", "#9099a6", "#c7ccd4", "#adb5bd"]) {
			const ratio = contrastRatio(tintOver(parseColor(grey), 0.13), newBadge);
			expect(ratio, `${grey} badge vs *New* badge reads ${ratio.toFixed(2)}:1`).toBeLessThan(1.2);
		}
	});

	it("still falls back whole", () => {
		// WHAT WOULD MAKE THIS FAIL: the uncoloured branch applying to the tint and
		// not the text. Same defect the old code had for a CSS colour name, moved
		// one level down: a coloured number on a background that renders nothing.
		expect(stageTone("papayawhip")).toEqual(stageTone(""));
		expect(stageTone(null)).toEqual(stageTone(""));
	});
});

describe("a new stage is born with a colour of its own", () => {
	it("puts it in the middle of the widest unused arc", () => {
		// WHAT WOULD MAKE THIS FAIL: returning any free hue rather than the FURTHEST
		// one. With red, yellow and green in use the wheel has two 60° gaps and one
		// 240° gap; anything but the middle of the wide one is a worse answer that
		// still passes a naive "is it unused?" check.
		const hue = hueOf(nextStageColor(["#ff0000", "#ffff00", "#00ff00"]));
		expect(hue).toBeCloseTo(240, 0);
	});

	it("beats the seeded palette's own tightest spacing on a full default board", () => {
		// WHAT WOULD MAKE THIS FAIL: a fixed list of hexes. This is the case that
		// matters — a fresh site with all seven stages, where a manager adds an
		// eighth. Nine of the CRM palette's ten colours fail this; the seeded seven
		// are themselves only 40° apart at their tightest, so 40° is the bar the
		// board already sets for itself.
		const seeded = seededColours().map(([, hex]) => hex);
		const used = seeded.map(hueOf).filter((h) => h !== null);
		const hue = hueOf(nextStageColor(seeded));
		const worst = Math.min(...used.map((u) => hueGap(hue, u)));
		expect(worst, `the eighth stage lands ${worst.toFixed(0)}° from a seeded hue`).toBeGreaterThanOrEqual(40);
	});

	it("gives the ninth stage a different colour from the eighth", () => {
		// WHAT WOULD MAKE THIS FAIL: ignoring the argument and returning a constant.
		// Two stages created in a row is the ordinary way a board grows, and it is
		// the exact case a "next colour" that does not read the board gets wrong.
		const seeded = seededColours().map(([, hex]) => hex);
		const eighth = nextStageColor(seeded);
		const ninth = nextStageColor([...seeded, eighth]);
		expect(ninth).not.toBe(eighth);
		expect(hueGap(hueOf(ninth), hueOf(eighth))).toBeGreaterThan(20);
	});

	it("does not let a grey stage reserve a hue", () => {
		// WHAT WOULD MAKE THIS FAIL: treating *New* and *Closed* as occupying 208°
		// and 210°. They are 7 % and 11 % saturated — the reader sees two greys, not
		// two blues — so letting them fence off the blue quarter of the wheel would
		// spend the board's best remaining colour on nothing.
		expect(nextStageColor(["#6c757d", "#adb5bd", "#ffffff"])).toBe(nextStageColor([]));
	});

	it("ignores values that are not colours instead of throwing", () => {
		// WHAT WOULD MAKE THIS FAIL: assuming every stage has a readable colour. The
		// field is a plain `Data` column and the whole point of this change is that
		// rows already exist with nothing in it — so the first real board this runs
		// on is one where some entries are empty.
		const out = nextStageColor([null, undefined, "", "red", "#gggggg", "#4263eb"]);
		expect(parseColor(out), `not a colour: ${out}`).not.toBeNull();
		expect(hueGap(hueOf(out), hueOf("#4263eb"))).toBeGreaterThan(40);
	});

	it("returns a colour every stored value can be read back as", () => {
		// WHAT WOULD MAKE THIS FAIL: emitting `hsl(...)` or `rgb(...)`. The seven
		// seeded stages are six-digit hex and parseColor accepts nothing but hex, so
		// a stage created with an `hsl()` string would round-trip through the
		// database and come back as the fallback — uncoloured, which is precisely
		// the state this change exists to prevent.
		expect(nextStageColor([])).toMatch(/^#[0-9a-f]{6}$/);
	});
});

describe("the board sends that colour when it creates a stage", () => {
	it("passes one to so_stage_save", () => {
		// WHAT WOULD MAKE THIS FAIL: the generator landing and the board still
		// sending three fields. That is the state S3 reported — the server has
		// accepted a colour all along and the caller never supplied one — and every
		// test above stays green through it, because they call the helper directly.
		const call = board.slice(board.indexOf("so_stage_save"), board.indexOf("await load()"));
		expect(call, "no so_stage_save call found").not.toBe("");
		expect(/color:\s*nextStageColor\(/.test(call), "so_stage_save is called with no colour").toBe(
			true
		);
	});

	it("computes it from the stages already on the board", () => {
		// WHAT WOULD MAKE THIS FAIL: calling it with no argument. It would still
		// return a valid colour — the accent — for every stage anyone ever adds, so
		// the board would hand out one repeated colour and look fixed while being
		// exactly as broken as before.
		expect(
			/nextStageColor\(\s*stages\.value\.map\(/.test(board),
			"nextStageColor is not fed the board's own stages"
		).toBe(true);
		expect(
			/import \{[^}]*\bnextStageColor\b[^}]*\} from "\.\.\/\.\.\/composables\/color\.js"/.test(board),
			"the board does not import nextStageColor"
		).toBe(true);
	});

	it("still reaches a server that stores it", () => {
		// WHAT WOULD MAKE THIS FAIL: the endpoint dropping the parameter. The wire
		// has two ends and this file can see both; a colour sent to an endpoint that
		// ignores it is the same screen defect with a longer stack trace.
		expect(api).toMatch(/def so_stage_save\([^)]*\bcolor\b/);
		expect(api).toMatch(/doc\.color = color/);
	});
});
