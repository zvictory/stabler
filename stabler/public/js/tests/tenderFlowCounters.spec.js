import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/TenderFlow.vue"), "utf8");

/**
 * The same source with every comment removed.
 *
 * The ternary ban below needs this and the first version of it did not have it:
 * the screen's own comment QUOTES the defect it stopped shipping —
 * `stuck === 1 ? t("step") : t("steps")` — so a check run over the raw file was
 * red against the fixed component. Banning a shape rather than a value has to
 * let the code say which shape it stopped using; stageColor.spec.js needed the
 * identical correction for a hex it had banned by spelling.
 */
const code = src
	.replace(/\/\*[\s\S]*?\*\//g, "")
	.replace(/<!--[\s\S]*?-->/g, "")
	.replace(/\/\/[^\n]*/g, "");

/**
 * The process flow's counters and its two per-row verdicts — prompt 16's W9,
 * W10, W14, W15 and W16.
 *
 * Measured on the whole file 2026-09-02: four counters, four human notes, and
 * ZERO `ds-kpi-q` — the fourth screen in this package with a `ds-kpis` strip and
 * the only one with no rule line anywhere. The absence is loudest on
 * `Bottleneck`, whose value was the answer to a computation the reader cannot
 * see: `_tender_flow.bottleneck` picks the step exceeding its threshold by the
 * greatest RATIO, and on seed data that is `priced` (7.0/3 = 2.33x) rather than
 * `sourcing`, which is 8.5 days further over (22.5/14 = 1.61x). A reader
 * comparing the gaps picks the wrong step.
 *
 * DOM-less per vitest.config.mjs: the counter builder and the two note
 * functions are lifted out of the source and run for real, because "the caption
 * does not change when the count does" is a claim about behaviour that no
 * source-text match can make. The source assertions that remain are only about
 * WIRING — a helper that works and is called by nothing looks identical to
 * these tests otherwise.
 */

/** Source of one top-level function, from its declaration to its closing brace. */
function fnSrc(name) {
	const m = src.match(new RegExp(`^(?:async )?function ${name}\\([\\s\\S]*?^\\}`, "m"));
	expect(m, `TenderFlow.vue has no top-level ${name}()`).not.toBeNull();
	return m[0];
}

/** Lift the named functions into one scope with fakes for what they close over. */
function lift(names) {
	const scope = {
		t: (s) => s,
		// Supplied so a regression that puts the step's NAME back into the strip
		// fails on the assertion that says so, rather than on a ReferenceError.
		stepLabel: (key) => ({ priced: "Bid pricing", sourcing: "Quotation gathering" })[key] || key,
	};
	const keys = Object.keys(scope);
	const body = names.map(fnSrc).join("\n");
	return new Function(...keys, `${body}\nreturn {${names.join(",")}};`)(...keys.map((k) => scope[k]));
}

/** The five rows `_tender_flow.step_rows` produces from seed data, measured
 *  2026-09-02 by executing it against `seed_tender_demo.DEMO_LOTS`. */
const SEED = [
	{ stage: "seen", open: 2, unmeasured: 0, avg_days: 2.0, worst_days: 3, worst_state: "today", worst_over: 0, sla_days: 3, sla_source: "default", state: "edge" },
	{ stage: "go", open: 2, unmeasured: 0, avg_days: 4.5, worst_days: 5, worst_state: "today", worst_over: 0, sla_days: 5, sla_source: "default", state: "edge" },
	{ stage: "sourcing", open: 2, unmeasured: 0, avg_days: 22.5, worst_days: 26, worst_state: "crit", worst_over: 12, sla_days: 14, sla_source: "default", state: "out" },
	{ stage: "priced", open: 2, unmeasured: 0, avg_days: 7.0, worst_days: 8, worst_state: "crit", worst_over: 5, sla_days: 3, sla_source: "default", state: "out" },
	{ stage: "submitted", open: 2, unmeasured: 2, avg_days: null, worst_days: null, worst_state: "info", worst_over: 0, sla_days: 30, sla_source: "default", state: "unknown" },
];
const SEED_PAYLOAD = { in_process: 10, unmeasured: 2, bottleneck: "priced" };

/** One row, overridden. Keeps each case to the fields it is actually about. */
const row = (over) => ({ ...SEED[0], ...over });

/** Rows where exactly `n` of the five are over their threshold. */
function withStuck(n) {
	return SEED.map((r, i) => ({ ...r, state: i < n ? "out" : "in" }));
}

describe("every counter states the rule that produced it", () => {
	it("gives all four a rule line, not just a friendly note", () => {
		// WHAT WOULD MAKE THIS FAIL: the module's signature going missing on the
		// one screen about thresholds. Prompts 13, 14 and 15 all carry
		// `ds-kpi-q`; this was the only `ds-kpis` strip in the package with
		// none, so four numbers claimed things the reader could not check.
		for (const k of lift(["counters", "bottleneckCounter"]).counters(SEED_PAYLOAD, SEED)) {
			expect(k.rule, `counter ${k.key} states no rule`).toBeTruthy();
			expect(k.note, `counter ${k.key} lost its human note`).toBeTruthy();
		}
	});

	it("keeps the rule line untranslated, the way the sibling boards do", () => {
		// WHAT WOULD MAKE THIS FAIL: wrapping the query in t(). `count(step.state
		// = out)` is the same sentence in every language, and DirectorBoard and
		// TenderFunnel both write it raw. Putting it through the catalogue would
		// add five rows per counter that no translator can improve.
		const { counters, bottleneckCounter } = lift(["counters", "bottleneckCounter"]);
		const rules = counters(SEED_PAYLOAD, SEED).map((k) => k.rule);
		expect(rules).toEqual([
			"sum(step.open) · stage ∈ working",
			"count(step.state = out)",
			"max(avg_days ÷ sla_days) · ratio, not gap",
			"count(entered_at is null)",
		]);
		expect(bottleneckCounter(SEED_PAYLOAD, SEED).rule).toContain("ratio");
	});

	it("draws the rule line the strip is built from", () => {
		// WHAT WOULD MAKE THIS FAIL: the builder growing a `rule` key that the
		// template never renders — the fix present, wired to nothing, and every
		// assertion above still green because they call the builder directly.
		expect(src).toMatch(/class="ds-kpi-q">\{\{ k\.rule \}\}/);
		expect(src).toMatch(/const kpis = computed\(\(\) => counters\(/);
	});
});

describe("no counter's wording depends on how many things it counted", () => {
	it("reads the same caption for one step as for four", () => {
		// WHAT WOULD MAKE THIS FAIL: `stuck === 1 ? t("step") : t("steps")`
		// coming back. It is correct for English and wrong for Russian and
		// Uzbek, which need a third form for 2-4 against 5+ — and with five
		// working steps every one of 1, 2, 3, 4 and 5 is reachable, so the wrong
		// form is not theoretical. The i18n layer has interpolation and no
		// plural support, so the counter is written not to need one.
		const { counters, bottleneckCounter } = lift(["counters", "bottleneckCounter"]);
		void bottleneckCounter;
		const capsFor = (n) => counters(SEED_PAYLOAD, withStuck(n)).map((k) => k.cap);
		expect(capsFor(1)).toEqual(capsFor(4));
		expect(capsFor(0)).toEqual(capsFor(5));
	});

	it("says how many of how many, so the noun is pinned to a constant", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping the denominator and going back to
		// a bare count beside a noun. "2 / 5 steps" also says more than "2
		// steps": two of the five working steps are over, which is the sentence
		// a director is actually reading for.
		const { counters, bottleneckCounter } = lift(["counters", "bottleneckCounter"]);
		void bottleneckCounter;
		const stuck = counters(SEED_PAYLOAD, SEED).find((k) => k.key === "stuck");
		expect(stuck.val).toBe("2 / 5");
		expect(stuck.cap).toBe("steps");
		const unmeasured = counters(SEED_PAYLOAD, SEED).find((k) => k.key === "unmeasured");
		expect(unmeasured.val).toBe("2 / 10");
	});

	it("never chooses a user-facing string with a ternary, anywhere in the file", () => {
		// WHAT WOULD MAKE THIS FAIL: the shape returning somewhere else — the
		// Refresh button's label was the second instance and would have survived
		// a fix aimed only at the counter. Banning the shape is what makes the
		// rule hold for strings nobody has written yet.
		//
		// Comments stripped, and that is not cosmetic: run over the raw file
		// this assertion is red against the FIXED component, because the fix's
		// own comment quotes the ternary it removed.
		expect(/\?\s*t\([^)]*\)\s*:\s*t\(/.test(code), "a t() string is picked by a ternary").toBe(false);
	});
});

describe("the bottleneck is quantified in the strip and named on its row", () => {
	it("shows the ratio the rule is made of rather than the step's name", () => {
		// WHAT WOULD MAKE THIS FAIL: the counter naming the step again. The
		// screen then states its single most important finding twice in two
		// shapes — a word in a counter and an unlabelled 3px stripe on a row —
		// and connects them nowhere. The number here is the one thing the stripe
		// cannot carry, and the row carries the word.
		const { counters, bottleneckCounter } = lift(["counters", "bottleneckCounter"]);
		const neck = bottleneckCounter(SEED_PAYLOAD, SEED);
		expect(neck.val).toBe("2.33×");
		expect(neck.cap).toBe("of its threshold");
		const strip = counters(SEED_PAYLOAD, SEED)
			.map((k) => `${k.label} ${k.val} ${k.cap} ${k.note}`)
			.join(" ");
		expect(strip, "the strip names the step as well as the row").not.toContain("Bid pricing");
	});

	it("quotes the ratio of the step the server chose, not of the worst gap", () => {
		// WHAT WOULD MAKE THIS FAIL: computing the ratio from whichever row
		// looks worst here. `sourcing` is 8.5 days over and `priced` only 4, so
		// a strip that re-derived its own answer would print 1.61x beside a row
		// marked two columns away — two numbers for one finding, which is the
		// defect this screen's own header warns about.
		const { bottleneckCounter } = lift(["counters", "bottleneckCounter"]);
		expect(bottleneckCounter({ bottleneck: "sourcing" }, SEED).val).toBe("1.61×");
	});

	it("says none today when no step is over its threshold", () => {
		// WHAT WOULD MAKE THIS FAIL: printing a ratio of a step that is not
		// over. A quiet pipeline has no bottleneck and must say so in words; a
		// "1.00x" would read as a finding.
		const { bottleneckCounter } = lift(["counters", "bottleneckCounter"]);
		const quiet = bottleneckCounter({ bottleneck: null }, SEED);
		expect(quiet.val).toBe("—");
		expect(quiet.cap).toBe("none today");
		expect(quiet.sev).toBe("ok");
	});

	it("names it in the row it describes, exactly once", () => {
		// WHAT WOULD MAKE THIS FAIL: the row keeping only its stripe. A colour
		// with no word is unreadable to a screen reader and unexplained to
		// everyone else; a reader who sorts or scans by eye has nothing to join
		// the counter to.
		expect(src).toMatch(/v-if="row\.stage === data\?\.bottleneck" class="flow-neck"/);
		expect(src.match(/t\("Bottleneck"\)/g)?.length, "Bottleneck is written more than once").toBe(2);
	});
});

describe("the worst deal carries a verdict, and none where there is nothing to judge", () => {
	it("says how far over the threshold the worst deal is", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving `Worst` a bare number. Four of five
		// columns carry a state and this one did not, while the function that
		// would judge it — `_tender_sla.overdue_by` — was written, documented
		// and called by nothing outside its own tests.
		const { worstNote } = lift(["worstNote"]);
		expect(worstNote(row({ worst_state: "crit", worst_over: 12, worst_days: 26, sla_days: 14 }))).toBe(
			"12 days over"
		);
	});

	it("marks a deal sitting exactly on its threshold", () => {
		// WHAT WOULD MAKE THIS FAIL: showing a verdict only for the red rows.
		// Two of the five seeded steps read *At the edge* on average and each
		// holds a deal sitting exactly on its limit — the case a director can
		// still act on today, and the one an average hides.
		const { worstNote } = lift(["worstNote"]);
		expect(worstNote(row({ worst_state: "today", worst_over: 0, worst_days: 3, sla_days: 3 }))).toBe(
			"at the limit"
		);
		expect(worstNote(row({ worst_state: "soon", worst_over: 0, worst_days: 2, sla_days: 3 }))).toBe(
			"near the limit"
		);
		expect(worstNote(row({ worst_state: "info", worst_over: 0, worst_days: 1, sla_days: 14 }))).toBe(
			"Within"
		);
	});

	it("stays silent when there is no threshold or no measurement", () => {
		// WHAT WOULD MAKE THIS FAIL: printing "Within" under a step nobody
		// tracks, or under a step whose deals have no stage stamp. Both would be
		// the screen inventing a reassurance out of missing data — the one thing
		// this module's own header forbids.
		const { worstNote } = lift(["worstNote"]);
		expect(worstNote(row({ worst_days: null, worst_state: "info", sla_days: 30 }))).toBe("");
		expect(worstNote(row({ worst_days: 900, worst_state: "info", sla_days: null }))).toBe("");
	});

	it("renders the verdict beside the number it judges", () => {
		// WHAT WOULD MAKE THIS FAIL: the helper landing and the Worst cell
		// staying a bare number, with every assertion above still green.
		const cell = src.slice(src.indexOf('<th class="ds-td-num flow-c-w">{{ t("Worst")'), src.indexOf("</tbody>"));
		expect(cell).toMatch(/worstNote\(row\)/);
		expect(cell).toMatch(/:data-sev="row\.worst_state"/);
	});
});

describe("a threshold says whether it is the tenant's or the box's", () => {
	it("distinguishes a company's own number from the built-in one", () => {
		// WHAT WOULD MAKE THIS FAIL: the panel foot promising "thresholds come
		// from Stabler Settings, per company" while every row renders
		// identically. A director reading `threshold 14 days` could not tell
		// whether their company chose it.
		const { slaNote } = lift(["slaNote"]);
		expect(slaNote(row({ sla_source: "tenant" }))).toBe("set for this company");
		expect(slaNote(row({ sla_source: "default" }))).toBe("matches the built-in default");
	});

	it("claims only what the wire can prove", () => {
		// WHAT WOULD MAKE THIS FAIL: wording that asserts provenance. Measured
		// 2026-09-02: `stage_sla_for` returns the DEFAULT dict verbatim for a
		// company with no settings row, so a tenant who typed the built-in
		// number is indistinguishable from one who typed nothing. "matches the
		// built-in default" is true either way; "not configured" would not be.
		const { slaNote } = lift(["slaNote"]);
		expect(slaNote(row({ sla_source: "default" })), "the wording claims provenance").not.toMatch(
			/configur|never set|unset/i
		);
	});

	it("says a switched-off step was switched off, not never tracked", () => {
		// WHAT WOULD MAKE THIS FAIL: rendering threshold-0 the same as a step
		// nobody configured. A 0 is an administrator taking a step out of
		// tracking on purpose; showing it as an absence hides the decision and
		// invites the next reader to "fix" it back to the default.
		const { slaNote } = lift(["slaNote"]);
		expect(slaNote(row({ sla_source: "off", sla_days: null }))).toBe("switched off for this company");
	});

	it("renders it under every threshold, not only the overridden ones", () => {
		// WHAT WOULD MAKE THIS FAIL: showing the source line only when it is a
		// tenant's. A line that appears on some rows reads as an exception
		// report; the question "is this mine?" has to be answered for all five.
		const cell = src.slice(src.indexOf('t("not tracked")'), src.indexOf("</tbody>"));
		expect(cell).toMatch(/\{\{ slaNote\(row\) \}\}/);
		expect(cell, "the source line is behind a v-if").not.toMatch(/v-if="[^"]*"[^>]*>\s*\{\{ slaNote/);
	});
});
