import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const funnel = readFileSync(resolve(here, "../pages/tender/TenderFunnel.vue"), "utf8");
const board = readFileSync(resolve(here, "../pages/tender/DirectorBoard.vue"), "utf8");
const overview = readFileSync(resolve(here, "../pages/tender/TenderOverview.vue"), "utf8");

/**
 * F10 (docs/design/prompts/15-pipeline-overview.md, S1) — `/tender/portfolio`
 * rendered ten counters: the director board's own six, plus TenderFunnel's four,
 * because `<TenderFunnel pipeline-strip :selected="phase" ...>` on DirectorBoard
 * never set `mode`, and the prop's default was `"full"` — the same branch
 * TenderOverview.vue opts into on purpose with an explicit `mode="full"`.
 *
 * Two counters with the same label ("Risk"), the same caption and the same rule
 * string then showed different numbers (2 vs 1) side by side on one page — the
 * exact shape F10 forbids.
 *
 * The fix flips the DEFAULT rather than touching DirectorBoard.vue: this prompt
 * (15) owns TenderFunnel.vue; DirectorBoard.vue is prompt 14's screen, edited by
 * a different agent in this session. Flipping the default means a host that asks
 * for nothing gets the light render, and TenderOverview keeps its full render
 * because it asks for it explicitly — no change needed on either host's template.
 *
 * P1-6 (coordinator review, 2026-09-02): "the light render" first meant "chevron
 * only" -- the same `v-if="props.mode === 'full'"` wrapped BOTH the KPI counters
 * (the actual collision above) AND the whole stage-grid section beneath them,
 * which DirectorBoard never had its own copy of and still needs: its own
 * template comment already promises "stage grid, funnel and chevron strip are
 * in their own component" (DirectorBoard.vue). The silent host lost the stage
 * boxes, their rule lines, the submitted/urgent chip and the go() drill-down,
 * and nothing caught it. Only the counters are gated now.
 */
describe("F10 — TenderFunnel does not draw its counters on a host that never asked for them", () => {
	it("gates only the KPI counter strip behind mode=full, not the stage grid", () => {
		// WHAT WOULD MAKE THIS FAIL: restoring `default: "full"`. That is the exact
		// line that made every silent (non-opting) host draw the KPI counters and
		// stage boxes, which is how the board ended up with ten counters instead of
		// its own six.
		expect(
			/mode:\s*\{\s*type:\s*String,\s*default:\s*"full"\s*\}/.test(funnel),
			"mode still defaults to full"
		).toBe(false);

		// The gate string appears EXACTLY ONCE in the whole file, and it sits on
		// the KPI block's own opening tag -- not on a <template> wrapping the KPI
		// block and the stage grid together. A single shared count also survives
		// the case where the gate moves back onto a wrapping template that
		// happens to be spelled the same way somewhere else in the file.
		const gate = /v-if="props\.mode === 'full'"/g;
		const hits = funnel.match(gate) || [];
		expect(hits.length, "expected exactly one mode==='full' gate in the file").toBe(1);
		expect(funnel).toMatch(/<div v-if="props\.mode === 'full'" class="ds-kpis"/);

		// WHAT WOULD MAKE THIS FAIL: re-wrapping the stage-grid section in the
		// mode==='full' gate -- P1-6's actual defect. Its own opening tag must
		// carry no v-if directly; a second copy of the gate reappearing on an
		// outer <template> around it is caught above (the count would read 2,
		// not 1) rather than here.
		expect(
			funnel.includes('class="ds-panel funnel-block"'),
			"the stage-grid section moved or was renamed"
		).toBe(true);
		expect(funnel).toMatch(/<section class="ds-panel funnel-block">/);
	});

	it("DirectorBoard's mount still does not pass mode, so it now gets the light render", () => {
		// WHAT WOULD MAKE THIS FAIL: DirectorBoard.vue starting to pass an explicit
		// `mode="full"`. This test does not touch DirectorBoard.vue -- it only
		// proves the OTHER half of the fix still holds: the host this prompt is not
		// allowed to edit still relies on the default, so flipping the default is a
		// complete fix and not half of one.
		const mount = board.match(/<TenderFunnel\b[^>]*>/s);
		expect(mount, "TenderFunnel is not mounted on the director board").not.toBeNull();
		expect(mount[0]).not.toMatch(/\bmode=/);
	});

	it("TenderOverview keeps the full render by asking for it explicitly", () => {
		// The one host this prompt owns must be UNAFFECTED by the default flip.
		const mount = overview.match(/<TenderFunnel\b[^>]*>/s);
		expect(mount, "TenderFunnel is not mounted on the overview").not.toBeNull();
		expect(mount[0]).toMatch(/mode="full"/);
	});
});
