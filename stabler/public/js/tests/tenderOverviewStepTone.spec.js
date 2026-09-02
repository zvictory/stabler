import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/TenderOverview.vue"), "utf8");
const css = readFileSync(resolve(here, "../../css/stabler-modernist.css"), "utf8");

/**
 * F14 (docs/design/prompts/15-pipeline-overview.md, S4) — `stepTone` coloured
 * a step's number:
 *
 *     const stepTone = (row) => {
 *         if (row.state === "out") return "crit";
 *         if (row.state === "empty") return "mute";
 *         return null;
 *     };
 *
 * `unknown` ("Not measurable" — open work, no stamp to measure it by) fell
 * through to the same `null` as `in` ("Within"). Measured against seed data
 * 2026-09-02: the "Bid submitted" step held two lots with no stamp and
 * rendered in the exact colour of a healthy step, beside a dash where the
 * wait figure should be. The chip text was already honest (`stateLabel`
 * prints "Not measurable"); the pixels were not.
 *
 * `stepTone` is a pure function of `row.state` — lifted out of the source and
 * called directly, no DOM needed.
 */
function liftStepTone() {
	const fn = src.match(/const stepTone = \(row\) => \{[\s\S]*?\n\};/);
	expect(fn, "TenderOverview.vue has no top-level stepTone").not.toBeNull();
	return new Function(`${fn[0]}\nreturn stepTone;`)();
}

describe("F14 — the unknown/not-measurable state is not painted like a healthy one", () => {
	const stepTone = liftStepTone();

	it("gives `unknown` a tone distinct from `in`'s", () => {
		// WHAT WOULD MAKE THIS FAIL: `unknown` falling back through to the same
		// `null` as `in` -- the exact collision S4 measured on seed data.
		expect(stepTone({ state: "unknown" })).not.toBe(stepTone({ state: "in" }));
		expect(stepTone({ state: "unknown" })).not.toBeNull();
	});

	it("reuses the muted tone the SLA badge already gives this state, not a new colour", () => {
		// stabler-modernist.css already colours .ds-sla[data-state="unknown"]
		// and [data-state="empty"] identically (--ds-tx3), with a comment
		// explaining why on purpose: neither is a warning, both mark the edge of
		// what is known, and a warning colour would flag a line with no problem.
		// `mute` is the one existing .ds-stage tone carrying that same meaning --
		// it is already what `empty` gets, one line above the fix.
		expect(stepTone({ state: "unknown" })).toBe("mute");
		const emptyRule = css.match(/\.ds-sla\[data-state="empty"\]\s*\{[^}]*\}/);
		const unknownRule = css.match(/\.ds-sla\[data-state="unknown"\]\s*\{[^}]*\}/);
		expect(emptyRule, "the sibling badge's empty rule moved or was renamed").not.toBeNull();
		expect(unknownRule, "the sibling badge's unknown rule moved or was renamed").not.toBeNull();
		expect(unknownRule[0].match(/--ds-tx3/)).toBeTruthy();
		expect(emptyRule[0].match(/--ds-tx3/)).toBeTruthy();
	});

	it("leaves the states this fix does not touch exactly as they were", () => {
		expect(stepTone({ state: "out" })).toBe("crit");
		expect(stepTone({ state: "empty" })).toBe("mute");
		expect(stepTone({ state: "in" })).toBeNull();
	});
});
