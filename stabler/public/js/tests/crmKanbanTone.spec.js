import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { contrastRatio, parseColor, stageTone, tintOver } from "../composables/color.js";

const here = dirname(fileURLToPath(import.meta.url));
const deals = readFileSync(resolve(here, "../pages/crm/Deals.vue"), "utf8");

/**
 * The CRM kanban had the same three colour defects as the contract board — the
 * ones prompt 18 filed as S3 — and one the board did not have.
 *
 *     :style="{ background: colorHex(col.status.color) + '22',
 *               color: colorHex(col.status.color),
 *               border: `1px solid ${colorHex(col.status.color)}55` }"
 *
 * It survived the board's fix on 2026-09-02 because the two kanbans store colour
 * differently — the CRM stores a NAME resolved through `KANBAN_COLORS`, the
 * contract board stores hex — so nothing that repaired one touched the other.
 *
 * That difference makes the CONCATENATION latent rather than live: `colorHex`
 * only ever returns a six-digit hex from a closed list, so `+ '22'` does produce
 * a valid colour today. It is one non-palette hex away from not doing so, which
 * is why it goes; it is not what was broken on screen.
 *
 * What was broken on screen is measured below, and it is worse here than on the
 * board: every one of the ten palette colours fails WCAG AA as its own text on
 * its own tint, AND six of the ten fail on the plain white card — where the
 * deal's own money figure is printed. The board had no such site.
 */

/** The ten palette colours, read from the component so the test cannot drift. */
function paletteColours() {
	const block = deals.match(/const KANBAN_COLORS = \[([\s\S]*?)\n\];/);
	expect(block, "KANBAN_COLORS has moved").not.toBeNull();
	const rows = [...block[1].matchAll(/name: "([a-z]+)",\s*hex: "(#[0-9a-f]{6})"/g)].map((m) => [
		m[1],
		m[2],
	]);
	expect(rows.length, "no palette colours parsed").toBe(10);
	return rows;
}

/** The rgb triple inside an `rgb(...)`/`rgba(...)` string. */
function channels(css) {
	const m = css.match(/rgba?\((\d+), (\d+), (\d+)/);
	expect(m, `not an rgb() string: ${css}`).not.toBeNull();
	return m.slice(1, 4).map(Number);
}

const WHITE = [255, 255, 255];
/** `22` is the alpha the old code concatenated: 0x22 / 0xff. */
const OLD_ALPHA = 34 / 255;

describe("the measurements that made this worth changing", () => {
	it("records that no palette colour reads on its own tint", () => {
		// WHAT WOULD MAKE THIS FAIL: nothing in the source — this is arithmetic on
		// the palette, kept because it is the argument for the change. The same
		// measurement on the contract board found 0 of 7 passing; here it is 0 of
		// 10, between 2.58:1 (yellow) and 4.41:1 (purple) against a bar of 4.5.
		//
		// So "use the colour unless it is bad" would have changed nothing, exactly
		// as on the board. The colour has to be darkened.
		for (const [name, hex] of paletteColours()) {
			const rgb = parseColor(hex);
			const ratio = contrastRatio(rgb, tintOver(rgb, OLD_ALPHA));
			expect(ratio, `${name} (${hex}) read ${ratio.toFixed(2)}:1 on its own tint`).toBeLessThan(
				4.5
			);
		}
	});

	it("records that the deal's money figure failed on the plain white card", () => {
		// WHAT WOULD MAKE THIS FAIL: nothing in the source. This is the site the
		// contract board does not have — the card prints the deal's value in the
		// column's colour, on white, in the file's largest bold type, and six of
		// the ten palette colours are under AA there: blue 3.68, green 3.30,
		// yellow 2.94, orange 3.56, teal 3.74, cyan 3.68.
		//
		// Recorded as a set rather than a count, because the interesting fact is
		// WHICH ones: the four that pass are the dark ones, so the defect was
		// invisible to anyone whose columns happened to be red, purple or pink.
		const failing = paletteColours()
			.filter(([, hex]) => contrastRatio(parseColor(hex), WHITE) < 4.5)
			.map(([name]) => name);
		expect(failing).toEqual(["blue", "green", "yellow", "orange", "teal", "cyan"]);
	});
});

describe("every palette colour now reads on both surfaces", () => {
	it("clears AA as text on its own tint", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping the darkening step, or tinting at a
		// different alpha than the one the contrast is checked against. The count
		// chip, the avatar and the probability badge are all this shape.
		for (const [name, hex] of paletteColours()) {
			const tone = stageTone(hex);
			const ratio = contrastRatio(channels(tone.text), tintOver(parseColor(hex), 0.13));
			expect(ratio, `${name} reads ${ratio.toFixed(2)}:1 on its tint`).toBeGreaterThanOrEqual(4.5);
		}
	});

	it("clears AA on the white card too, with the same value", () => {
		// WHAT WOULD MAKE THIS FAIL: needing a second helper for the white site.
		// The tint is the harder surface — it is lighter than nothing but darker
		// than white is — so a colour dark enough to read on it is dark enough to
		// read on white, measured at 5.12:1 (yellow) to 6.34:1 (purple). One tone
		// covers both, which is why no second function exists.
		for (const [name, hex] of paletteColours()) {
			const ratio = contrastRatio(channels(stageTone(hex).text), WHITE);
			expect(ratio, `${name} reads ${ratio.toFixed(2)}:1 on white`).toBeGreaterThanOrEqual(4.5);
		}
	});
});

describe("the CRM draws its kanban colours from the shared helper", () => {
	it("imports it rather than growing a second copy", () => {
		// WHAT WOULD MAKE THIS FAIL: reimplementing the darkening here. money.js
		// says of its own precision rule that it is "the single source of truth" —
		// three screens had each written the UZS fraction-digit ternary and two of
		// the three were wrong. This is the same rule about the same kind of thing,
		// and the two kanbans having diverged is precisely how this file kept a
		// defect the other one had already fixed.
		expect(
			/import \{[^}]*\bstageTone\b[^}]*\} from "\.\.\/\.\.\/composables\/color\.js"/.test(deals),
			"Deals.vue does not import stageTone"
		).toBe(true);
	});

	it("stops concatenating an alpha onto the hex", () => {
		// WHAT WOULD MAKE THIS FAIL: `+ '22'` or `}55` coming back, under any
		// variable name. Anchored to the shape and not to `colorHex`, because on
		// the contract board renaming the variable walked straight past the first
		// version of this test.
		expect(/\+\s*["'][0-9a-f]{2}["']/i.test(deals), "a two-digit alpha is concatenated again").toBe(
			false
		);
		expect(
			/\}[0-9a-f]{2}`/i.test(deals),
			"a two-digit alpha is appended in a template literal"
		).toBe(false);
	});

	it("wires all four text sites, not just the one that was reported", () => {
		// WHAT WOULD MAKE THIS FAIL: fixing the count chip and leaving the card.
		// The chip is what the report named; the money figure, the owner avatar and
		// the probability badge are the same defect on the same screen, and the
		// money figure is the one a reader actually needs.
		for (const site of [
			"kanban-count-chip",
			"kanban-card-value",
			"kanban-avatar",
			"kanban-prob-badge",
		]) {
			const at = deals.indexOf(site);
			expect(at, `${site} has gone`).toBeGreaterThan(-1);
			const style = deals.slice(at, deals.indexOf(">", at));
			expect(/toneOf\(col\)/.test(style), `${site} still colours itself by hand`).toBe(true);
		}
	});

	it("keeps the column rule on the tone as well", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving `borderTop` on the raw hex. It is the
		// one place the undarkened colour is still correct — a 3px rule is not text
		// — but it must come from the same call, or an uncoloured column gets a
		// grey rule over a colourless header.
		expect(
			/borderTop: `3px solid \$\{toneOf\(col\)\.line\}`/.test(deals),
			"the rule is drawn by hand"
		).toBe(true);
	});
});

describe("a status with no colour does not impersonate the grey one", () => {
	it("resolves the palette without falling back to grey", () => {
		// WHAT WOULD MAKE THIS FAIL: `toneOf` routing through `colorHex`, whose
		// fallback is `#6b7280` — which is ALSO the palette's own `gray`. That is
		// S3's problem 1 verbatim, in a second file: a column nobody coloured and a
		// column someone deliberately made grey render identically, and the picker
		// shows no difference either.
		const at = deals.indexOf("const toneOf = ");
		expect(at, "no toneOf helper").toBeGreaterThan(-1);
		const helper = deals.slice(at, deals.indexOf("\n", at));
		expect(/colorHex\(/.test(helper), "toneOf still routes through the grey fallback").toBe(false);
	});

	it("does not spend a token that only resolves on the other screen", () => {
		// WHAT WOULD MAKE THIS FAIL: the uncoloured tone going back to
		// `var(--ds-ln2)` / `var(--ds-tx2)`, which is what it was written as first.
		// Those resolve for the contract board — TenderPage wraps it in `.stbl-ds`,
		// where the tokens are defined — and NOT here: App.vue renders this page
		// under a plain `.page`. An undefined custom property makes the whole
		// declaration invalid, so the column would silently lose its badge and its
		// count rather than render them plainly, and no test would have said so.
		//
		// The scoping itself needs a browser and is not claimed. What is claimed is
		// that the shared helper does not depend on a token at all.
		const source = readFileSync(resolve(here, "../composables/color.js"), "utf8");
		const uncoloured = source.slice(
			source.indexOf("const UNCOLOURED"),
			source.indexOf("});", source.indexOf("const UNCOLOURED"))
		);
		expect(uncoloured, "UNCOLOURED has moved").not.toBe("");
		expect(/var\(--/.test(uncoloured), "the uncoloured tone depends on a CSS custom property").toBe(
			false
		);
	});

	it("renders as uncoloured rather than as the grey entry", () => {
		// WHAT WOULD MAKE THIS FAIL: the helper's fallback becoming a colour again.
		// Behavioural, because the source assertion above only bans one spelling.
		const none = stageTone("");
		const grey = stageTone("#6b7280");
		for (const key of ["line", "tint", "border", "text"]) {
			expect(none[key], `an uncoloured column renders the grey entry's ${key}`).not.toBe(grey[key]);
		}
	});
});

describe("the picker shows the uncoloured state instead of claiming grey", () => {
	/**
	 * `CRM Deal Status.color` is a **Select**, not free text, and its options are
	 * thirteen: black, gray, blue, green, red, pink, orange, amber, yellow, cyan,
	 * teal, violet, purple. `KANBAN_COLORS` carries ten of them — `black`, `amber`
	 * and `violet` are missing — so three perfectly legal values, storable from
	 * the Frappe desk or the CRM app's own screens, resolve to nothing here.
	 *
	 * Which makes "no colour" a state the picker really can reach, and it was
	 * reporting it as `gray`: `colorHex`'s fallback is `#6b7280`, the palette's own
	 * grey. The reader saw a grey dot in the menu, opened the picker, and found no
	 * swatch selected — two screens disagreeing about the same column, neither of
	 * them right.
	 *
	 * Read from the doctype JSON on 2026-09-02. The list is NOT asserted here: it
	 * lives in the `crm` app, outside this repository, so a test that read it would
	 * fail on any clone without that app installed. The behaviour below holds for
	 * any value the palette cannot draw, which is the claim that matters.
	 */

	/** The "Color" item in the column's ⋯ menu — the dot the reader sees first.
	 *  Anchored to the CALL, not the name: `openColorPicker` alone matches the
	 *  function declaration 600 lines above, so the slice ran over the wrong
	 *  region and the test could not fail. */
	function menuItem() {
		const at = deals.indexOf('@click.stop="openColorPicker(');
		expect(at, "the Color menu item has gone").toBeGreaterThan(-1);
		const item = deals.slice(at, deals.indexOf("</button>", at));
		expect(item.length, "the menu item sliced empty").toBeGreaterThan(50);
		return item;
	}

	/** The colour picker panel's markup. */
	function pickerBlock() {
		const at = deals.indexOf("kanban-color-picker");
		expect(at, "the colour picker has gone").toBeGreaterThan(-1);
		return deals.slice(at, deals.indexOf("</div>", at));
	}

	it("does not paint the menu dot with the grey fallback", () => {
		// WHAT WOULD MAKE THIS FAIL: the trigger going back to `colorHex(...)`. That
		// is the whole report — a column whose colour this palette cannot draw got a
		// grey dot, which is indistinguishable from a column somebody deliberately
		// made grey, and grey is one of the ten the picker offers.
		const item = menuItem();
		expect(/colorHex\(/.test(item), "the menu dot still uses the grey fallback").toBe(false);
		expect(/paletteHex\(col\.status\.color\)/.test(item), "the dot ignores the palette").toBe(true);
	});

	it("marks the dot as unset rather than leaving it blank", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping the background to "" and rendering
		// nothing. An empty 12px circle is not a state, it is a rendering accident —
		// the reader cannot tell it from a slow load. The dashed outline says the
		// colour is absent on purpose.
		const item = menuItem();
		expect(/kanban-color-none/.test(item), "the unset dot has no marker class").toBe(true);
		expect(/\.kanban-color-none\s*\{[^}]*dashed/.test(deals), "no dashed style for the unset dot").toBe(
			true
		);
	});

	it("shows the same state inside the picker, where the choice is made", () => {
		// WHAT WOULD MAKE THIS FAIL: fixing only the menu dot. The picker is where
		// the manager decides, and with none of the ten outlined it reported nothing
		// at all — "no colour" and "a colour I cannot draw" looked identical to
		// "the outline failed to render".
		expect(
			/v-if="!paletteHex\(col\.status\.color\)"/.test(pickerBlock()),
			"the picker shows nothing when the colour does not resolve"
		).toBe(true);
	});

	it("shows it without offering to write it", () => {
		// WHAT WOULD MAKE THIS FAIL: making the indicator a <button> that calls
		// updateColColor with "". The field is a Select whose thirteen options do
		// NOT include a blank, so clearing a colour would write a value outside the
		// column's own vocabulary — through an endpoint that validates none of it.
		// The ask was to SHOW the state; a control that sets it is a different
		// change, and one the doctype does not currently support.
		const block = pickerBlock();
		const at = block.indexOf("v-if=\"!paletteHex");
		expect(at, "there is no unset indicator to check").toBeGreaterThan(-1);
		const indicator = block.slice(at);
		const upTo = indicator.indexOf(">");
		expect(/@click/.test(indicator.slice(0, upTo)), "the unset indicator is clickable").toBe(false);
		expect(/<span/.test(block.slice(0, block.indexOf("v-if=\"!paletteHex"))), "not a span").toBe(true);
	});

	it("leaves the ten real swatches writing real colour names", () => {
		// WHAT WOULD MAKE THIS FAIL: the indicator displacing the v-for, or the
		// swatches losing their handler. Everything above is about reporting a
		// state; none of it may cost the picker its actual job.
		const block = pickerBlock();
		expect(/v-for="c in KANBAN_COLORS"/.test(block), "the ten swatches are gone").toBe(true);
		expect(
			/@click\.stop="updateColColor\(col\.status, c\.name\)"/.test(block),
			"the swatches no longer set a colour"
		).toBe(true);
	});
});
