import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/TenderFunnel.vue"), "utf8");

/**
 * F16 (docs/design/prompts/15-pipeline-overview.md, S6) — the chevron's second
 * layer (the quote-set bar, the phase note, the rule) lives in
 * `<span v-if="hovered === c.key" class="pipe-pop">`, revealed only by
 * `@mouseenter`/`@mouseleave` on the cell and `@focus`/`@blur` on the chevron
 * button. Focus already reaches it (tab to the button); a pointer that cannot
 * hover -- a touchscreen -- has no path in: tapping the chevron button fires
 * `@click="pick(c)"`, which selects/navigates in the SAME gesture, so even
 * where a tap transiently focuses the button, the popover has no chance to be
 * read before the click moves the screen on.
 *
 * Fix: a second, small, purpose-built button inside the same cell,
 * `.pipe-info`, wired to a new `toggleDetails(row)` that only ever writes
 * `hovered` -- it never calls `pick()` and never emits `select`. A native
 * `<button>` is both keyboard-reachable on its own and, being a SEPARATE tap
 * target from the chevron, gives touch a way in that carries no navigation
 * side effect.
 *
 * `toggleDetails` is a pure function of `hovered` and one row -- lifted out of
 * the source and called directly, no DOM needed. The `emit` spy proves the
 * behavioural half of the claim: NOT selecting/navigating is exactly the
 * property a template-only test cannot see.
 */
function liftToggleDetails(scope) {
	const fn = src.match(/function toggleDetails\(row\) \{[\s\S]*?\n\}/);
	expect(fn, "TenderFunnel.vue has no top-level toggleDetails").not.toBeNull();
	const keys = Object.keys(scope);
	return new Function(...keys, `${fn[0]}\nreturn toggleDetails;`)(...keys.map((k) => scope[k]));
}

function harness() {
	const hovered = { value: "" };
	const emitted = [];
	const scope = { hovered, emit: (name, ...args) => emitted.push([name, ...args]) };
	return { hovered, emitted, toggleDetails: liftToggleDetails(scope) };
}

describe("F16 — a second tap target opens the popover without selecting the phase", () => {
	it("reveals the popover for a row nothing was hovering", () => {
		// WHAT WOULD MAKE THIS FAIL: toggleDetails not existing, or not writing
		// to the same `hovered` ref the template keys `.pipe-pop`'s v-if off of.
		const h = harness();
		h.toggleDetails({ key: "sourcing" });
		expect(h.hovered.value).toBe("sourcing");
	});

	it("closes it again on a second activation of the same row", () => {
		// A touch device has no hover-out equivalent -- without a toggle, a
		// popover opened by tapping this button could only ever be closed by
		// opening a DIFFERENT row's, which reads as broken on the one row that
		// is still open.
		const h = harness();
		h.toggleDetails({ key: "sourcing" });
		h.toggleDetails({ key: "sourcing" });
		expect(h.hovered.value).toBe("");
	});

	it("switches to a different row rather than closing on a stale key", () => {
		const h = harness();
		h.toggleDetails({ key: "sourcing" });
		h.toggleDetails({ key: "priced" });
		expect(h.hovered.value).toBe("priced");
	});

	it("never selects or navigates -- this is the entire point of the second button", () => {
		// WHAT WOULD MAKE THIS FAIL: toggleDetails calling pick(row) or emitting
		// "select" itself, which would make the info button just a confusing
		// second way to do what the chevron button already does, rather than a
		// side-effect-free path to the popover.
		const h = harness();
		h.toggleDetails({ key: "sourcing" });
		h.toggleDetails({ key: "priced" });
		h.toggleDetails({ key: "priced" });
		expect(h.emitted).toEqual([]);
	});
});

describe("F16 — the template wires a real, independent tap target", () => {
	it("adds .pipe-info as a sibling of .pipe-chev inside .pipe-cell", () => {
		const cellStart = src.indexOf('class="pipe-cell"');
		expect(cellStart, ".pipe-cell not found").toBeGreaterThan(-1);
		const popStart = src.indexOf("pipe-pop", cellStart);
		const cell = src.slice(cellStart, popStart);
		expect(cell).toMatch(/class="pipe-chev"/);
		expect(cell, "no separate .pipe-info button inside the cell").toMatch(/class="pipe-info"/);
		// A real <button>, not a span/div with a click handler: keyboard reach
		// (Tab + Enter/Space) comes free only from the native element.
		const infoAt = cell.indexOf('class="pipe-info"');
		const infoTag = cell.slice(Math.max(0, infoAt - 60), infoAt);
		expect(infoTag).toMatch(/<button/);
	});

	it("the info button calls toggleDetails, not pick", () => {
		const infoAt = src.indexOf('class="pipe-info"');
		const infoButton = src.slice(infoAt, infoAt + 300);
		expect(infoButton).toMatch(/@click="toggleDetails\(c\)"/);
		expect(infoButton, "the info button also selects/navigates").not.toMatch(/pick\(/);
	});

	it("announces its open/closed state to assistive tech", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping aria-expanded -- a screen reader
		// would have no way to tell whether activating this button opens or
		// closes the popover.
		const infoAt = src.indexOf('class="pipe-info"');
		const infoButton = src.slice(infoAt, infoAt + 300);
		expect(
			infoButton,
			"no aria-expanded -- a screen reader can't tell if the popover is open"
		).toMatch(/:aria-expanded="String\(hovered === c\.key\)"/);
	});

	it("names which cell's details this opens, and what it controls", () => {
		// F16 ruling (coordinator review, 2026-09-02): the bare ℹ glyph is
		// suppressed by a screen reader at default verbosity, and aria-expanded
		// with no aria-controls does not say WHAT it expands -- neither gap is
		// closed by aria-expanded alone (the test above).
		//
		// WHAT WOULD MAKE THIS FAIL: the aria-label reverting to a fixed string
		// ("Details") that does not distinguish cells, "Show details for
		// {label}" (rejected: "Show" contradicts aria-expanded="true" once open,
		// and "for {label}" needs case agreement the t() layer cannot do -- see
		// the CSS comment above .pipe-info), or aria-controls pointing at an id
		// the popover span itself does not carry.
		const infoAt = src.indexOf('class="pipe-info"');
		const infoButton = src.slice(infoAt, infoAt + 400);
		expect(infoButton).toMatch(/:aria-label="t\('Details: \{label\}', \{ label: c\.label \}\)"/);
		expect(infoButton, 'aria-label reads "Show ... for" instead of "Details:"').not.toMatch(/Show/);
		expect(infoButton).toMatch(/:aria-controls="'pipe-pop-' \+ c\.key"/);

		const popAt = src.indexOf('class="pipe-pop"');
		expect(popAt, ".pipe-pop not found").toBeGreaterThan(-1);
		const popTag = src.slice(Math.max(0, popAt - 120), popAt);
		expect(popTag, ".pipe-pop carries no id for aria-controls to point at").toMatch(
			/:id="'pipe-pop-' \+ c\.key"/
		);
	});
});
