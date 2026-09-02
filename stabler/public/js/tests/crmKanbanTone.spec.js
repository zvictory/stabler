import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "fs";
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
	// Not a literal count: the parse must account for every entry in the block,
	// so an entry whose shape the regex cannot read reports instead of vanishing.
	const declared = (block[1].match(/hex:/g) || []).length;
	expect(rows.length, `parsed ${rows.length} of ${declared} palette entries`).toBe(declared);
	expect(declared, "the palette is empty").toBeGreaterThan(0);
	return rows;
}

/** The rgb triple inside an `rgb(...)`/`rgba(...)` string. */
function channels(css) {
	const m = css.match(/rgba?\((\d+), (\d+), (\d+)/);
	expect(m, `not an rgb() string: ${css}`).not.toBeNull();
	return m.slice(1, 4).map(Number);
}

const WHITE = [255, 255, 255];
/** The ten the palette held on 2026-09-02, before `black`, `amber` and `violet`
 *  were added. The two measurements below are records of that day and are scoped
 *  to it: one that silently re-scopes itself as the palette grows is a record of
 *  nothing. */
const THEN = ["gray", "blue", "green", "yellow", "orange", "red", "purple", "pink", "teal", "cyan"];
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
		//
		// `black`, added later, is the one colour that always read on its own tint
		// (13.56) — it was broken the OTHER way, rendering as grey because the
		// palette carried no entry for it at all.
		for (const [name, hex] of paletteColours().filter(([n]) => THEN.includes(n))) {
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
		//
		// Scoped to the ten the palette held that day. It has thirteen now, and a
		// measurement that silently re-scopes itself as the palette grows is not a
		// record of anything. (`amber`, added later, reads 3.19 and would have been
		// a seventh.)
		const failing = paletteColours()
			.filter(([name]) => THEN.includes(name))
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

describe("the palette draws every colour the column may hold", () => {
	/** The thirteen `CRM Deal Status.color` Select options, read 2026-09-02. */
	const RECORDED = [
		"black", "gray", "blue", "green", "red", "pink", "orange",
		"amber", "yellow", "cyan", "teal", "violet", "purple",
	];

	/** The doctype's own options when the `crm` app is beside this one, else the
	 *  recorded list. Both branches assert — this never passes by omission, the
	 *  way `make check`'s own eslint gate says a gate must not. */
	function selectOptions() {
		const at = resolve(
			here,
			"../../../../../crm/crm/fcrm/doctype/crm_deal_status/crm_deal_status.json"
		);
		if (!existsSync(at)) return RECORDED;
		const field = JSON.parse(readFileSync(at, "utf8")).fields.find((f) => f.fieldname === "color");
		expect(field, "CRM Deal Status has no colour field any more").toBeTruthy();
		return String(field.options || "").split("\n").filter(Boolean);
	}

	it("carries a hex for every option, so none can fall through to grey", () => {
		// WHAT WOULD MAKE THIS FAIL: the palette drifting behind the doctype again.
		// It held ten of thirteen — `black`, `amber` and `violet` were legal,
		// storable from the Frappe desk or the CRM app's own screens, and resolved
		// to nothing here, so all three rendered as the grey fallback: the palette's
		// own `gray`. A column really coloured violet and a column nobody coloured
		// at all looked identical.
		const known = new Set(paletteColours().map(([name]) => name));
		const missing = selectOptions().filter((o) => !known.has(o));
		expect(missing, `the column may be ${missing.join(", ")} and the picker cannot draw it`).toEqual(
			[]
		);
	});

	it("offers nothing the column cannot actually hold", () => {
		// WHAT WOULD MAKE THIS FAIL: adding a swatch for a colour the Select refuses.
		// save_deal_status validates none of this, so an invalid value would reach
		// doc.save and throw there — a picker whose swatches sometimes error.
		const legal = new Set(selectOptions());
		const extra = paletteColours().map(([name]) => name).filter((n) => !legal.has(n));
		expect(extra, `the picker offers ${extra.join(", ")}, which the field rejects`).toEqual([]);
	});

	it("renders the three the way the CRM app itself does", () => {
		// WHAT WOULD MAKE THIS FAIL: inventing hexes. crm's own parseColor is
		// `text-${color}-600`, with black on its darkest ink token and gray/green on
		// 700 — so the same status is one colour on the CRM app's screens and another
		// here unless these match. `black` is gray-900 rather than #000000: the app
		// does not use pure black either, and the palette is Tailwind throughout.
		const hexes = Object.fromEntries(paletteColours());
		expect(hexes.amber, "amber is not Tailwind amber-600").toBe("#d97706");
		expect(hexes.violet, "violet is not Tailwind violet-600").toBe("#7c3aed");
		expect(hexes.black, "black is not Tailwind gray-900").toBe("#111827");
	});

	it("records that the three tighten the palette, and why that is still right", () => {
		// WHAT WOULD MAKE THIS FAIL: nothing in the source. Kept because it is the
		// argument AGAINST this change, measured rather than waved away.
		//
		// `amber` sits between yellow and orange by definition and `violet` beside
		// purple, so adding them costs separation: purple/violet reads ΔE 10.6 and
		// yellow/amber 13.2 against the previous worst pair, orange/red at 21.2.
		// Under ~10 is where two colours stop being tellable apart.
		//
		// It is still the right trade, because the alternative was not "keep them
		// apart" — it was rendering all three AS GREY, a separation of exactly zero
		// from a colour already in the palette. And 600 is the best available shade,
		// not merely the faithful one: violet-700 reads 9.1 and amber-700 drops to
		// 9.0 against orange, both worse than what shipped.
		const hexes = Object.fromEntries(paletteColours());
		const de = (a, b) => {
			const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
			const lab = (rgb) => {
				const [r, g, b] = rgb.map((v) => {
					v /= 255;
					return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
				});
				const X = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047;
				const Y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
				const Z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883;
				return [116 * f(Y) - 16, 500 * (f(X) - f(Y)), 200 * (f(Y) - f(Z))];
			};
			const [la, lb] = [lab(channels(stageTone(a).text)), lab(channels(stageTone(b).text))];
			return Math.hypot(...la.map((v, i) => v - lb[i]));
		};
		expect(de(hexes.purple, hexes.violet)).toBeGreaterThan(10);
		expect(de(hexes.yellow, hexes.amber)).toBeGreaterThan(10);
		// The state they came from: identical to a colour already on the board.
		expect(de(hexes.gray, "#6b7280")).toBe(0);
	});
});

describe("the picker's colour names reach the catalogues", () => {
	/**
	 * The swatch tooltip was `:title="t(c.name)"` — a key computed at runtime.
	 *
	 * Dynamic `t()` is not a defect in itself and this SPA uses it in roughly two
	 * hundred places; it works whenever the key is a literal SOMEWHERE, because the
	 * harvester (`stabler.translations.harvest.run`) scans source for literal
	 * `t("…")` and appends what it finds. These thirteen were a literal nowhere.
	 *
	 * Measured 2026-09-02: all thirteen names absent from all five catalogues, in
	 * both casings — 13 of 13 — so every swatch tooltip rendered in English
	 * whatever language the user had picked. The palette grew from ten to thirteen
	 * that same day and the gap grew with it.
	 */

	const LANGS = ["en", "ru", "uz", "uzc", "tr"];

	/**
	 * `{key: translation}` for one catalogue.
	 *
	 * A real CSV scan, not a split on the first comma: the catalogues quote
	 * conditionally (261-399 of ~6 600 rows carry a quote, measured 2026-09-02), so
	 * a naive split turns `"Foo, bar",…` into the key `"Foo` — which would report a
	 * key as missing that is present, or worse, silently pass over one that is not.
	 */
	function catalogue(lang) {
		const raw = readFileSync(resolve(here, `../../../translations/${lang}.csv`), "utf8");
		const out = {};
		let row = [];
		let cell = "";
		let quoted = false;
		for (let i = 0; i < raw.length; i++) {
			const ch = raw[i];
			if (quoted) {
				if (ch !== '"') cell += ch;
				else if (raw[i + 1] === '"') (cell += '"'), i++;
				else quoted = false;
			} else if (ch === '"') quoted = true;
			else if (ch === ",") (row.push(cell), (cell = ""));
			else if (ch === "\n") {
				row.push(cell);
				if (row[0]) out[row[0]] = row[1] ?? "";
				(row = []), (cell = "");
			} else if (ch !== "\r") cell += ch;
		}
		if (cell || row.length) {
			row.push(cell);
			if (row[0]) out[row[0]] = row[1] ?? "";
		}
		return out;
	}

	it("names each colour with a literal key, not one computed at runtime", () => {
		// WHAT WOULD MAKE THIS FAIL: `t(c.name)` coming back, under any spelling.
		// The harvester cannot see a computed key, so the string never reaches a
		// catalogue and no amount of translating fixes it — the tooltip stays
		// English in all four other languages, silently, forever.
		const block = deals.match(/const KANBAN_COLORS = \[([\s\S]*?)\n\];/);
		expect(block, "KANBAN_COLORS has moved").not.toBeNull();
		const labels = [...block[1].matchAll(/label: t\("([^"]+)"\)/g)].map((m) => m[1]);
		expect(labels.length, "not every palette entry carries a literal label").toBe(
			(block[1].match(/hex:/g) || []).length
		);
	});

	it("uses that label in the picker rather than recomputing the key", () => {
		// WHAT WOULD MAKE THIS FAIL: the labels landing and the template still
		// calling t(c.name) — the fix present, wired to nothing, and the test above
		// still green because it only reads the array.
		const at = deals.indexOf("kanban-color-swatch");
		expect(at, "the swatches have gone").toBeGreaterThan(-1);
		const swatch = deals.slice(at, deals.indexOf("</button>", at));
		expect(/:title="c\.label"/.test(swatch), "the swatch does not use the literal label").toBe(true);
		expect(/t\(c\.name\)/.test(deals), "a colour name is still translated by a computed key").toBe(
			false
		);
	});

	it("carries every one of those keys in all five catalogues, translated", () => {
		// WHAT WOULD MAKE THIS FAIL: adding a colour and not translating it — which
		// is exactly how the palette reached thirteen untranslated names. The rule
		// this encodes is the i18n skill's: a feature does not land with a
		// user-facing string missing from any of the five.
		//
		// `en` is the source catalogue, so its target equals its key; the other four
		// must be non-empty and DIFFERENT from the English, or the row is a
		// placeholder someone appended and never filled — the state `Not set` was in
		// until today.
		const block = deals.match(/const KANBAN_COLORS = \[([\s\S]*?)\n\];/);
		const labels = [...block[1].matchAll(/label: t\("([^"]+)"\)/g)].map((m) => m[1]);
		expect(labels.length, "no labels to check").toBeGreaterThan(0);
		for (const lang of LANGS) {
			const cat = catalogue(lang);
			const missing = labels.filter((k) => !cat[k]);
			expect(missing, `${lang}.csv is missing ${missing.join(", ")}`).toEqual([]);
			if (lang === "en") continue;
			const untranslated = labels.filter((k) => cat[k] === k);
			expect(untranslated, `${lang}.csv still shows English for ${untranslated.join(", ")}`).toEqual(
				[]
			);
		}
	});
});
