import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const funnel = readFileSync(resolve(here, "../pages/tender/TenderFunnel.vue"), "utf8");
const api = readFileSync(resolve(here, "../../../api/tender.py"), "utf8");

/**
 * F11 (docs/design/prompts/15-pipeline-overview.md, S1) — the "Risk" counter's
 * printed rule was `"deadline < 48h · act_now"`. Measured against the server:
 *
 *     urgent = _deal_deadlines(deal, company, intake)["risk"] == "risk"
 *
 * and `_milestone()` (api/tender.py) sets `status = "risk"` on `days < 0` --
 * a milestone whose date has already passed -- with a SEPARATE branch for
 * `days <= 7` that is labelled `"warn"`, not `"risk"`. There is no 48-hour
 * threshold anywhere in the computation; the printed rule described a number
 * that does not exist in the code that produces the counter.
 *
 * P1-7 (coordinator review, 2026-09-02): the first fix -- `"any milestone ·
 * days < 0"` -- was still incomplete on two counts, both measured against
 * the server:
 *
 *  1. `_milestone()` checks `if done: status = "good"` BEFORE `elif days < 0`,
 *     so a DONE milestone is "good" however far past its own date -- the rule
 *     needs "not done" or it describes deals the server does not flag.
 *  2. `urgent` is computed only `if stage in ("go", "sourcing", "priced",
 *     "submitted")` (tender.py) -- DirectorBoard's own `at_risk` loops every
 *     deal with NO stage filter, a different population under a similarly-
 *     named counter, so this rule must name its own scope rather than drop
 *     it to look like a shared one.
 */
describe("F11 — the Risk counter's rule line describes what it actually counted", () => {
	it("no longer claims a 48-hour threshold that the server does not compute", () => {
		// WHAT WOULD MAKE THIS FAIL: the stale string coming back. It is not just
		// imprecise -- 48h and "the nearest deadline has already passed" describe
		// two different sets of deals, and a director reading "48h" would expect
		// the count to fall as a deadline is met, when in fact it only falls once
		// a deadline is OVERDUE.
		expect(funnel).not.toMatch(/deadline < 48h/);
	});

	it("states the actual threshold the server's own source computes, complete", () => {
		// Cross-checked against api/tender.py rather than asserted in isolation:
		// a rule string that merely stops saying "48h" without saying something
		// TRUE would still fail the design prompt's own test ("a counter's rule
		// line describes what it counted"), just less visibly.
		const milestoneFn = api.slice(
			api.indexOf("def _milestone("),
			api.indexOf("def _deal_deadlines(")
		);
		expect(milestoneFn, "_milestone() moved or was renamed").toMatch(
			/elif days < 0:\s*\n\s*status = "risk"/
		);
		// WHAT WOULD MAKE THIS FAIL: `if done:` no longer guarding `status = "good"`
		// ahead of the days check -- the point of "not done" in the rule string is
		// that this exact guard exists and fires first.
		expect(milestoneFn, "the done-first guard moved or was removed").toMatch(
			/if done:\s*\n\s*status = "good"/
		);

		// The KPI object's own `rule:` line, not a bare source-wide substring
		// match -- anchored to the "urgent" key so a rule string sitting on a
		// different counter cannot satisfy this assertion by accident.
		//
		// P1-7: a substring match on "days < 0" alone passed for
		// `rule: "bid deadline · days < 0"` -- true of one milestone, false of
		// the "any milestone" the server actually computes over, and silent
		// about `not done` entirely. The whole string, not a fragment of it, so
		// the next partial rule is red instead of a near-miss.
		const kpiBlock = funnel.slice(
			funnel.indexOf('key: "urgent"'),
			funnel.indexOf('key: "urgent"') + 900
		);
		expect(kpiBlock).toContain('rule: "open stage · any milestone · not done · days < 0"');
	});
});
