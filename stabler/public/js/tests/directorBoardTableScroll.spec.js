import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/DirectorBoard.vue"), "utf8");
const STYLE = src.slice(src.indexOf("<style scoped>"), src.indexOf("</style>"));

/**
 * Not one of prompt 14's seven assigned rows — a finding forwarded from the
 * prompt 16 agent, verified independently here, in this file, so it is this
 * agent's doc correction to make.
 *
 * Claimed (prompt 14 doc §9, "Measured"): ".board-scroll { overflow-x: auto
 * }": "the table scrolls, the page does not". False as stated: the doc
 * measured the container's own rule correctly but never checked whether the
 * TABLE inside it has anything to overflow WITH.
 *
 * Measured 2026-09-02: DirectorBoard.vue's own scoped style has exactly one
 * min-width in the whole file — `.board-phase-note { min-width: 200px; }`,
 * a flex-item constraint, nothing to do with the table. stabler-modernist.css
 * :389 sets `.stbl-ds .ds-table { width: 100%; ... }` and nothing overrides
 * it for this screen. A `width: 100%` table inside `overflow-x: auto` never
 * overflows — the nine columns compress instead, and the scroller has
 * nothing to scroll. Confirmed no min-width existed anywhere near .ds-table
 * before this file's own fix, below.
 *
 * The fix is min-width on .ds-table, in THIS file's own <style scoped> —
 * Vue scopes it to elements this component renders, so it changes nothing
 * for the .ds-table class stabler-modernist.css defines globally, and
 * min-width and width are different properties (no cascade/specificity
 * question): the browser takes max(width, min-width), so width: 100% still
 * governs on anything wider than the floor, and the floor only bites once
 * the container is narrower than it — which is exactly a phone.
 *
 * DOM-less, source-level only: there is no jsdom in this repo, so nothing
 * here proves a phone actually scrolls — only that the pieces needed for it
 * to are present. Guarded against vacuity per the prompt 16 agent's own
 * catch: the match array's length is asserted non-empty BEFORE the value is
 * read, so a regex that stops matching fails loudly instead of the test
 * quietly asserting nothing.
 */

describe("table-scroll — .board-scroll has something to scroll", () => {
	it(".board-scroll still just scrolls the table, not the page", () => {
		expect(STYLE).toMatch(/\.board-scroll\s*\{\s*overflow-x:\s*auto;\s*\}/);
	});

	it("the table itself has a min-width the container can overflow", () => {
		// WHAT WOULD MAKE THIS FAIL: removing the min-width rule (back to
		// today's bug — width: 100% with nothing to floor it), or moving it to
		// a class that is not actually the <table> (e.g. .board-scroll itself,
		// which already has somewhere to shrink to and would not force
		// overflow).
		const rules = [...STYLE.matchAll(/\.ds-table\s*\{[^}]*min-width:\s*(\d+)px[^}]*\}/g)];
		expect(rules.length, "no min-width rule for .ds-table found in DirectorBoard.vue's own scoped style").toBeGreaterThan(0);
		const minWidth = Number(rules[0][1]);
		// WHAT WOULD MAKE THIS FAIL: a floor narrower than a real phone (the
		// doc's own mobile artboard is 390×844) — that would compile and pass
		// the test above while still never triggering a scrollbar on the
		// device the row exists for.
		expect(minWidth).toBeGreaterThan(700);
	});
});
