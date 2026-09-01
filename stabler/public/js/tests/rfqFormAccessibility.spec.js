import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/rfq/RfqForm.vue"), "utf8");

/**
 * Two accessibility defects on the New RFQ form, both instances of one house
 * rule: a state or a meaning must be carried by more than one code, never by
 * colour or motion alone.
 *
 * 1. The "Create draft RFQ" button showed a Bootstrap `spinner-border` glyph
 *    while saving. A spinner is decorative — it has no accessible name and
 *    announces nothing to a screen reader. The fix is a label swap (the
 *    button's own text changes while `saving` is true) plus
 *    `:aria-busy="saving"` on the button, matching the pattern already used
 *    by `QuotationEntryDrawer.vue`'s save/submit buttons
 *    (`{{ saving ? t("Saving…") : t("Save draft") }}`).
 *
 * 2. Three required-field markers — tender lot, suppliers, requested items —
 *    were `<span class="text-danger">*</span>`: a red asterisk and nothing
 *    else. Colour alone fails a screen reader (nothing is announced) and a
 *    monochrome/colour-blind view (nothing but hue distinguishes it from
 *    decoration). The fix hides the bare glyph from assistive tech
 *    (`aria-hidden="true"`) and pairs it with a `.visually-hidden` span
 *    carrying the word "Required" — the same class already doing this job at
 *    `ProformaInvoices.vue:494` and the same `t()` key already shipped for
 *    `TenderDocuments.vue`'s own required marker.
 *
 * Same idiom as sourcingAwardPanel.spec.js: DOM-less, source-text assertions
 * against the raw `.vue` file, no `mount()`. A bare `toContain` check "passes
 * just as happily on a branch wired backwards", so assertions here either
 * COUNT occurrences or match the specific expression driving the behaviour
 * (the ternary, the binding, the marker-plus-equivalent pair) rather than a
 * substring's mere presence anywhere in the file.
 */

function anchor(marker, what) {
	const at = src.indexOf(marker);
	expect(at, `${what}: "${marker}" not found — has the markup moved?`).toBeGreaterThan(-1);
	return at;
}

describe("the create button reports busy state through text and aria, not a spinner glyph", () => {
	const clickCreateAt = anchor('@click="create"', "the create button");
	const buttonStart = src.lastIndexOf("<button", clickCreateAt);
	const buttonEnd = src.indexOf("</button>", clickCreateAt) + "</button>".length;
	const createButton = src.slice(buttonStart, buttonEnd);

	it("never renders a spinner-border glyph anywhere in this file", () => {
		// WHAT WOULD HAVE TO CHANGE for this to fail: any `spinner-border` class
		// reappearing in RfqForm.vue. The mandate is a label swap, never a
		// spinner, so the count must be exactly zero — not merely "fewer than
		// it used to be".
		expect((src.match(/spinner-border/g) || []).length).toBe(0);
	});

	it("binds aria-busy on the create button to the same `saving` flag that disables it", () => {
		// WHAT WOULD HAVE TO CHANGE: the `:aria-busy="saving"` binding being
		// removed, hardcoded to a literal, or moved off the create button onto
		// some other element.
		expect(createButton).toMatch(/:aria-busy="saving"/);
	});

	it("swaps the button's own label between the idle and the saving copy", () => {
		// WHAT WOULD HAVE TO CHANGE: the label reverting to an unconditional
		// `t("Create draft RFQ")`, or the ternary's two branches being swapped
		// or repointed at different translation keys.
		expect(createButton).toMatch(
			/saving\s*\?\s*t\(\s*"Creating…"\s*\)\s*:\s*t\(\s*"Create draft RFQ"\s*\)/,
		);
	});
});

describe("every required-field marker carries an accessible equivalent, not colour alone", () => {
	// A "marker": the red asterisk that visually flags a required field or
	// section, however it is attributed today. Counted with a global regex —
	// `.match()` is safe to reuse, unlike `.test()`/`toMatch()` on the same
	// global-flagged RegExp object, which carries mutable `lastIndex` state
	// across calls and silently skips matches on a second or third call.
	const markerRe = /<span class="text-danger"[^>]*>\*<\/span>/g;
	const markers = src.match(markerRe) || [];

	// An "accessible equivalent": the marker glyph is hidden from assistive
	// tech and immediately followed by a visually-hidden span carrying the
	// actual word "Required" — so the meaning reaches a screen reader as
	// text, once, instead of as an unannounced "*" or a redundant
	// "asterisk, Required".
	const equivalentReGlobal =
		/<span class="text-danger" aria-hidden="true">\*<\/span>\s*<span class="visually-hidden">\s*\{\{\s*t\(\s*"Required"\s*\)\s*\}\}\s*<\/span>/g;
	const equivalents = src.match(equivalentReGlobal) || [];

	it("finds at least one required marker to protect, so the count-match below isn't vacuous", () => {
		// WHAT WOULD HAVE TO CHANGE: every required-field marker being deleted
		// from the file. Without this floor, an empty file would satisfy the
		// count-match assertion below (0 === 0) without protecting anything.
		expect(markers.length).toBeGreaterThan(0);
	});

	it("pairs every marker with exactly one accessible equivalent — the two counts must match", () => {
		// WHAT WOULD HAVE TO CHANGE: this is a count COMPARISON, not a
		// hardcoded "3" — it generalises to a marker count nobody has picked
		// yet. A fourth required field added later WITH its visually-hidden
		// "Required" pair keeps this green (N markers, N equivalents); one
		// added WITHOUT the pair turns it red (N markers, N-1 equivalents).
		expect(equivalents.length).toBe(markers.length);
	});

	function equivalentPattern() {
		// Fresh RegExp instance per call — see the `lastIndex` note above.
		return /<span class="text-danger" aria-hidden="true">\*<\/span>\s*<span class="visually-hidden">\s*\{\{\s*t\(\s*"Required"\s*\)\s*\}\}\s*<\/span>/;
	}

	it.each([["Tender lot"], ["Suppliers to ask"], ["Requested items"]])(
		'names "%s" as required through text, not colour alone',
		(label) => {
			// WHAT WOULD HAVE TO CHANGE: this specific field's marker losing its
			// visually-hidden "Required" companion, even if the other two keep
			// theirs — this pinpoints which of the three regressed, which the
			// aggregate count-match test above cannot do by itself.
			const labelAt = anchor(`t("${label}")`, `the "${label}" heading`);
			const nearby = src.slice(labelAt, labelAt + 220);
			expect(nearby).toMatch(equivalentPattern());
		},
	);
});
