import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/DirectorBoard.vue"), "utf8");
const TEMPLATE = src.slice(src.indexOf("<template>"), src.indexOf("<style scoped>"));

/**
 * Acceptance row P14 (prompt 14, director board §11 / S6): phase filter and
 * route filters must be legible together, beside the table.
 *
 * Measured 2026-09-02: two filtering mechanisms sit on this screen and only
 * one explained itself. Phase (from the funnel) already renders a
 * `board-phase` bar with role="status" — label, lot count, a note, its own
 * Clear filter button — right above the table. Route filters
 * (tenderRouteFilters, 7 keys: stage/period/risk/due/status/from_date/
 * to_date) rendered as one ds-chip in #actions: `${key}: ${value}` joined by
 * " · " — raw filter KEYS (not labels) in the page header, far from the
 * table both mechanisms narrow. They compose (filteredRows applies both) but
 * a reader had no way to learn that, or which of the two removed which rows.
 *
 * The fix: reuse the phase bar's own exemplary shape verbatim (same
 * board-phase / role="status" / board-phase-kicker / board-phase-note /
 * board-phase-clear classes, zero new CSS) for the route filters too, placed
 * directly beside it and the table, with each raw key run through a
 * FILTER_LABELS-style lookup instead of printed as-is. The header #actions
 * chip is removed rather than duplicated.
 *
 * DOM-less per vitest.config.mjs: TEMPLATE substring/ordering checks for the
 * structural half, new-Function-lifted for filterLabel() itself (same idiom
 * as contractBoardReload.spec.js) for the mapping half.
 */

function liftFilterLabel() {
	const fn = src.match(/^const filterLabel = \(key\) => \([\s\S]*?\[key\] \|\| key\);$/m);
	expect(fn, "DirectorBoard.vue defines no top-level filterLabel(key)").not.toBeNull();
	return new Function("t", `${fn[0]}\nreturn filterLabel;`)((s) => s);
}

describe("P14 — every route filter key has a human label", () => {
	it("maps all seven tenderBoardFilters.js keys to the labels already in the catalogue", () => {
		// WHAT WOULD MAKE THIS FAIL: filterLabel missing a key (falls back to the
		// raw key for that one filter only) or mapping to a string not already
		// in en.csv, which would add a translation-catalogue key this row does
		// not need to spend.
		const filterLabel = liftFilterLabel();
		expect(filterLabel("stage")).toBe("Stage");
		expect(filterLabel("period")).toBe("Period");
		expect(filterLabel("risk")).toBe("Risk");
		expect(filterLabel("due")).toBe("Deadline");
		expect(filterLabel("status")).toBe("Result");
		expect(filterLabel("from_date")).toBe("From");
		expect(filterLabel("to_date")).toBe("To");
	});

	it("falls back to the raw key for anything unrecognized, rather than swallowing it", () => {
		// WHAT WOULD MAKE THIS FAIL: `{...}[key]` with no `|| key` fallback —
		// tenderBoardFilters.js's FILTER_KEYS could grow an eighth key a reader
		// of this file alone would not know about; printing "undefined:
		// value" is worse than printing the raw key.
		const filterLabel = liftFilterLabel();
		expect(filterLabel("something_new")).toBe("something_new");
	});

	it("filterSummary reads labels through filterLabel(), not the raw key", () => {
		// WHAT WOULD MAKE THIS FAIL: filterLabel existing but filterSummary
		// still interpolating the bare `key` — the exact S6 defect, just with
		// an unused label function sitting beside it.
		expect(src).toMatch(
			/const filterSummary = computed\(\(\) => activeTenderFilters\(filters\.value\)\.map\(\(\[key, value\]\) => `\$\{filterLabel\(key\)\}: \$\{value\}`\)\);/
		);
	});
});

describe("P14 — the route-filter summary sits beside the table, not in the header", () => {
	it("the header #actions chip is gone", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving the old #actions block in place
		// alongside a new bar — that would show the same information twice,
		// once raw and once legible, which is not what "legible together" asks
		// for.
		expect(TEMPLATE).not.toMatch(/#actions/);
	});

	it("a second board-phase-styled bar renders the route filters between the phase bar and the table", () => {
		const phaseAt = TEMPLATE.indexOf('v-if="phaseMeta" class="board-phase"');
		const portfolioAt = TEMPLATE.indexOf('class="ds-panel board-portfolio"');
		expect(phaseAt, "phase bar not found").toBeGreaterThan(-1);
		expect(portfolioAt, "board-portfolio not found").toBeGreaterThan(phaseAt);

		const between = TEMPLATE.slice(phaseAt, portfolioAt);
		// WHAT WOULD MAKE THIS FAIL: reusing a different class (inventing new
		// CSS for a bar the layer already solved once, one screen up) or
		// dropping role="status", which is what makes the phase bar's own
		// explanation reach a screen reader at all.
		expect(between).toMatch(/v-if="filterSummary\.length"\s+class="board-phase"\s+role="status"/);
		expect(between).toMatch(/t\("Filters"\)/);
		expect(between).toMatch(/filterSummary\.join\(" · "\)/);
		expect(between).toMatch(/t\("Clear filters"\)/);
		expect(between).toMatch(/@click="clearFilters"/);
	});
});
