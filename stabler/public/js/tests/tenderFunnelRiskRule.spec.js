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

	it("states the actual threshold the server's own source computes", () => {
		// Cross-checked against api/tender.py rather than asserted in isolation:
		// a rule string that merely stops saying "48h" without saying something
		// TRUE would still fail the design prompt's own test ("a counter's rule
		// line describes what it counted"), just less visibly.
		const milestoneFn = api.slice(api.indexOf("def _milestone("), api.indexOf("def _deal_deadlines("));
		expect(milestoneFn, "_milestone() moved or was renamed").toMatch(/elif days < 0:\s*\n\s*status = "risk"/);
		// The KPI object's own `rule:` line, not a bare source-wide substring
		// match -- anchored to the "urgent" key so a rule string sitting on a
		// different counter cannot satisfy this assertion by accident.
		const kpiBlock = funnel.slice(funnel.indexOf('key: "urgent"'), funnel.indexOf('key: "urgent"') + 600);
		expect(kpiBlock).toMatch(/rule:\s*"[^"]*days < 0[^"]*"/);
	});
});
