import { beforeAll, describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/MyTenders.vue"), "utf8");

/**
 * `/tender/my-tenders` (prompt 17) -- acceptance rows M7, M8, M9, M11, M12, M14
 * and the frontend half of M16. DOM-less per vitest.config.mjs
 * (`environment: "node"`, no jsdom, no @vue/test-utils): pure functions lifted
 * out of the component and run for real; template wiring checked against the
 * source text. What is NOT verified anywhere in this file: that the browser
 * actually renders any of this -- no component mounts, no CSS is computed, no
 * viewport is measured. M14 in particular is a claim about a scroll
 * CONTAINER existing with the right rule, not about scrolling happening.
 */

/** Lift a top-level `function name(...) { ... }` out of the component source
 *  and return it bound to the given scope (module-level free variables the
 *  function's body references, e.g. `t`). Lifting rather than re-typing means
 *  deleting or breaking the real function breaks this test, not a private copy. */
function lift(name, scope = {}) {
	const fn = src.match(new RegExp(`^function ${name}\\([^)]*\\)[\\s\\S]*?^\\}`, "m"));
	expect(fn, `MyTenders.vue has no top-level function ${name}()`).not.toBeNull();
	const keys = Object.keys(scope);
	return new Function(...keys, `${fn[0]}\nreturn ${name};`)(...keys.map((k) => scope[k]));
}

describe("M7 — the screen uses the house layer", () => {
	// WHAT WOULD MAKE THIS FAIL (all three): reverting any piece of the
	// migration. 17-my-tenders.md measured 1 `ds-*` token in 125 lines --
	// `Clear filters` -- and Bootstrap end to end everywhere else, including a
	// risk-colour map built in JS (`riskBadge`) that a template-only
	// `grep 'badge bg-'` cannot see. Each assertion below pins one half of
	// that: the house class present, the Bootstrap equivalent gone.
	it("wraps the table in a ds-panel, not a Bootstrap card", () => {
		expect(src).toMatch(/class="ds-panel"/);
		expect(src).not.toMatch(/class="card"/);
	});

	it("draws the table with ds-table, not table card-table", () => {
		expect(src).toMatch(/<table class="ds-table">/);
		expect(src).not.toMatch(/table card-table/);
	});

	it("colours risk through ds-chip[data-tone], not a Bootstrap badge map", () => {
		// P2-8 (coordinator review, 2026-09-02): `expect(src).toMatch(/ds-chip/)`
		// ran against the WHOLE file, and this file's own migration comment
		// (top of <script setup>) contains the literal substring "ds-chip" -- a
		// mutant reverting the risk chip to Bootstrap classes still had
		// "ds-chip" somewhere in the file (that comment) and passed. Sliced to
		// the risk cell specifically now, the same shape M11's chip test uses.
		const start = src.indexOf('<td><span class="ds-chip" :data-tone="riskTone');
		expect(start, "risk cell not found").toBeGreaterThan(-1);
		const riskCell = src.slice(start, src.indexOf("</td>", start) + 5);
		expect(riskCell).toMatch(/ds-chip/);
		expect(riskCell).not.toMatch(/bg-green-lt|bg-yellow-lt|bg-red-lt|riskBadge/);
	});

	it("still imports every risk state through ONE map, same shape as DirectorBoard's RISK_TONE", () => {
		// "import the pattern, not re-author it" (§S1): good -> ok, warn -> today,
		// risk -> crit is DirectorBoard's own RISK_TONE, verbatim.
		const m = src.match(/const RISK_TONE = (\{[^}]*\})/);
		expect(m, "no RISK_TONE map").not.toBeNull();
		const map = new Function(`return ${m[1]};`)();
		expect(map).toEqual({ good: "ok", warn: "today", risk: "crit" });
	});
});

describe("P2-7 (coordinator review) — SkeletonRows mounts in place of the table body, not inside it", () => {
	// 10-frontend.md: SkeletonRows' own root is a <tbody> (SkeletonRows.vue:10),
	// so nesting it inside another <tbody> renders <tbody><tbody> -- invalid
	// markup. Two shapes are correct: SkeletonRows as a sibling of
	// <tbody v-else>, both direct children of <table> (chosen here); or a
	// whole-block v-if/v-else swap whose loading branch carries its own
	// <table>. Measured 2026-09-01, 16 of 96 call sites nested wrongly --
	// "correct one when you next edit that file for another reason", and this
	// change rewrites the whole table, so it lands here.
	it("does not nest SkeletonRows inside a <tbody>", () => {
		// WHAT WOULD MAKE THIS FAIL: <tbody> immediately followed by
		// <SkeletonRows -- this file's own shape before the fix.
		expect(src).not.toMatch(/<tbody[^>]*>\s*<SkeletonRows/);
	});

	it("mounts SkeletonRows as a sibling of <tbody v-else>, both under <table>", () => {
		expect(src).toMatch(/<SkeletonRows v-if="loading"[^/]*\/>\s*<tbody v-else>/);
	});
});

describe("M8 — the active-stage chip is shown only while that filter is in effect", () => {
	// lift() runs inside beforeAll, not at describe-body top level: a missing
	// target throws, and a throw at describe-collection time aborts the WHOLE
	// FILE's collection in vitest (every other row's tests included), not just
	// this block's. beforeAll runs later, during execution, so a missing
	// stageChipLabel fails only this describe's tests.
	let stageChipLabel;
	beforeAll(() => {
		stageChipLabel = lift("stageChipLabel", { t: (s) => s });
	});

	it("says nothing while the stage's deal set has not resolved yet", () => {
		// WHAT WOULD MAKE THIS FAIL: keying the chip off the URL param alone, which
		// is the defect S2 reported -- between navigation and the second request
		// answering, funnelDeals is null, the table shows everything, and the old
		// code still prepended "Stage: X" because it only checked funnelStage.
		expect(stageChipLabel("sourcing", null, { sourcing: "Collecting quotations" })).toBe("");
	});

	it("says nothing once the second request has failed", () => {
		// WHAT WOULD MAKE THIS FAIL: a guard that only covers the loading window.
		// loadFunnelStage's catch sets funnelDeals back to null on failure -- the
		// exact same state as "not answered yet" -- so one guard must cover both.
		expect(stageChipLabel("sourcing", null, {})).toBe("");
	});

	it("names the stage once the filter is actually in effect", () => {
		expect(stageChipLabel("sourcing", new Set(["D1"]), { sourcing: "Collecting quotations" })).toBe(
			"Stage: Collecting quotations",
		);
	});

	it("says nothing when there is no stage in the URL at all", () => {
		expect(stageChipLabel("", new Set(), {})).toBe("");
	});

	it("is actually wired into filterSummary, not just defined", () => {
		// WHAT WOULD MAKE THIS FAIL: the helper landing unused, same failure mode
		// stageColor.spec.js found once already -- a fix present and wired to
		// nothing, every unit test above still green because they call the lifted
		// function directly.
		const body = src.slice(src.indexOf("const filterSummary"), src.indexOf("const filteredRows"));
		expect(body).toMatch(/stageChipLabel\(/);
	});
});

describe("M9 — the screen says whether it is showing everything or only your assignments", () => {
	let scopeSentence;
	beforeAll(() => {
		scopeSentence = lift("scopeSentence", { t: (s) => s });
	});

	it("says nothing before the first load has answered", () => {
		// WHAT WOULD MAKE THIS FAIL: defaulting oversight to false (or true).
		// `data` starts as `{ rows: [], currency: "" }` -- no oversight key -- so a
		// default would claim a scope for a fraction of a second before the real
		// value is known, which is a wrong claim about who is looking, however
		// briefly.
		expect(scopeSentence(undefined)).toBe("");
	});

	it("tells a sourcing user their list is scoped to their own assignments", () => {
		// WHAT WOULD MAKE THIS FAIL: the sentence going the other way, or reading
		// generically. S3's whole point is that the reader cannot currently tell
		// which of the two audiences they are -- "oversight unread" -- so the two
		// branches must say opposite, specific things.
		expect(scopeSentence(false)).toBe("Showing only tenders assigned to you.");
	});

	it("tells a director the list is the whole company", () => {
		expect(scopeSentence(true)).toBe("Showing every tender in the company.");
	});

	it("is wired into the #meta slot through its own v-if, unconditionally on filters", () => {
		// WHAT WOULD MAKE THIS FAIL: nesting it inside the filterSummary.length
		// guard, which is the OLD defect this file's own Turkish comment records
		// ("Şerit KOŞULSUZ") for the freshness stamp -- the scope sentence must not
		// regress into the same trap of only showing while a filter is active.
		// scopeLine (not scopeSentence) is what the template reads: a memoised
		// computed, the same shape every sibling span in #meta already uses,
		// rather than calling the function twice per render.
		const meta = src.slice(src.indexOf("#meta"), src.indexOf("</template>", src.indexOf("#meta")));
		expect(meta).toMatch(/<span v-if="scopeLine">\{\{\s*scopeLine\s*\}\}<\/span>/);
		const wiring = src.slice(src.indexOf("const scopeLine"), src.indexOf("const scopeLine") + 120);
		expect(wiring).toMatch(/scopeSentence\(data\.value\?\.oversight\)/);
	});
});

describe("M11 — a won or lost tender is distinguishable from an open one", () => {
	// resultTone/resultLabel are `const ... = (x) => ...;` one-liners (matching
	// riskTone/riskLabel's existing style right above them), and resultTone
	// closes over RESULT_TONE declared the line before -- lift() only handles
	// `function name() {...}`, and lifting resultTone alone would leave
	// RESULT_TONE undefined inside the isolated function, so both are pulled
	// out and declared together, same idea as contractBoardReload.spec.js
	// lifting `reqToken` alongside `load()`.
	let resultTone, resultLabel;
	beforeAll(() => {
		const map = src.match(/^const RESULT_TONE = \{[^}]*\};$/m);
		const tone = src.match(/^const resultTone = .*;$/m);
		const label = src.match(/^const resultLabel = .*;$/m);
		expect(map, "no RESULT_TONE map").not.toBeNull();
		expect(tone, "no resultTone").not.toBeNull();
		expect(label, "no resultLabel").not.toBeNull();
		const built = new Function(
			"t",
			`${map[0]}\n${tone[0]}\n${label[0]}\nreturn { resultTone, resultLabel };`,
		)((s) => s);
		resultTone = built.resultTone;
		resultLabel = built.resultLabel;
	});

	it("tones won and lost the same way DirectorBoard's RESULT_TONE does", () => {
		expect(resultTone("won")).toBe("ok");
		expect(resultTone("lost")).toBe("crit");
	});

	it("gives an open tender (empty result) no tone to render", () => {
		// WHAT WOULD MAKE THIS FAIL: mapping "" to a truthy tone. The row's own
		// `result` field is "" for an open tender (§S6) -- the template guards the
		// chip on `r.result`, so a falsy tone here is what keeps an open row chip-
		// less rather than drawing a fourth, meaningless colour.
		expect(resultTone("")).toBe(null);
	});

	it("labels each result as a capitalised word", () => {
		expect(resultLabel("won")).toBe("Won");
		expect(resultLabel("lost")).toBe("Lost");
	});

	it("renders the chip in the row, guarded on r.result", () => {
		// WHAT WOULD MAKE THIS FAIL: the helpers landing unused. §S6 measured
		// `result` present on every row and rendered nowhere; this pins that the
		// template actually consumes it, not just that the helpers exist.
		expect(src).toMatch(/v-if="r\.result"[^>]*class="ds-chip"[^>]*:data-tone="resultTone\(r\.result\)"/s);
	});

	it("tones a pending result too, matching DirectorBoard's own three-way map", () => {
		// P2-6 (coordinator review, 2026-09-02): RESULT_TONE was two-wide,
		// missing "pending" -- but _clean_intake normalizes result to
		// won/lost/pending (tender.py:1512), and that normalization runs before
		// sourcing_my_tenders ever reads intake.get("result"), so "pending" is a
		// real, reachable value on THIS endpoint, not only DirectorBoard's. The
		// old comment claiming result "is only ever '', 'won' or 'lost'" was
		// wrong and is corrected alongside this.
		expect(resultTone("pending")).toBe("today");
	});

	it("falls back to an amber Unverified chip when a result exists but is not evidence-backed", () => {
		// P1-3 (coordinator review, 2026-09-02): sourcing_my_tenders now gates
		// r.result on evidence["lifecycle"]["submitted"] (tender.py), so a
		// result set without a submitted bid arrives here as r.result === "" +
		// r.lifecycle.unverified_history === true -- the exact shape
		// DirectorBoard already renders as an "Unverified" chip. WHAT WOULD
		// MAKE THIS FAIL: no v-else-if branch (the row would go chip-less,
		// silently hiding that there IS unverified history), or one not
		// gated on r.lifecycle?.unverified_history specifically.
		const tenderCell = src.slice(src.indexOf("mt-tender"), src.indexOf("</div>", src.indexOf("mt-tender")));
		expect(tenderCell).toMatch(
			/v-else-if="r\.lifecycle\?\.unverified_history"[^>]*class="ds-chip"[^>]*data-tone="today"/s,
		);
		expect(tenderCell).toMatch(/t\("Unverified"\)/);
	});
});

describe("M12 — a failed load is distinguishable from \"no tenders match these filters\"", () => {
	/** A promise this test resolves/rejects by hand. */
	function deferred() {
		let resolve, reject;
		const promise = new Promise((res, rej) => {
			resolve = res;
			reject = rej;
		});
		return { promise, resolve, reject };
	}

	function liftLoad(scope) {
		const fn = src.match(/^async function load\(\)[\s\S]*?^\}/m);
		expect(fn, "MyTenders.vue has no top-level load()").not.toBeNull();
		const keys = Object.keys(scope);
		return new Function(...keys, `${fn[0]}\nreturn load;`)(...keys.map((k) => scope[k]));
	}

	function harness() {
		const activeCompany = { value: "Mikas" };
		const data = { value: { rows: [], currency: "" } };
		const loading = { value: false };
		const error = { value: "" };
		const errors = [];
		let pending;
		const scope = {
			activeCompany,
			data,
			loading,
			error,
			toast: { error: (m) => errors.push(m) },
			t: (s) => s,
			call: () => (pending = deferred()).promise,
		};
		return {
			...scope,
			errors,
			get pending() {
				return pending;
			},
			load: liftLoad(scope),
		};
	}

	it("records the failure on `error`, not only the toast", async () => {
		// WHAT WOULD MAKE THIS FAIL: catching straight into toast.error and
		// leaving `error` unset -- the pre-existing behaviour, and the reason a
		// failed load rendered the exact same "No tenders match these filters."
		// as an honest empty result (§5): nothing distinguished the two once the
		// toast had faded.
		const h = harness();
		const p = h.load();
		h.pending.reject(new Error("Tender module is not enabled for Mikas."));
		await p;
		expect(h.error.value).toBe("Tender module is not enabled for Mikas.");
		expect(h.loading.value).toBe(false);
	});

	it("clears a previous failure before the next attempt can be judged", async () => {
		// WHAT WOULD MAKE THIS FAIL: setting error and never resetting it -- a
		// stale failure would keep claiming "could not load" over a table that
		// loaded fine on the next auto-refresh.
		const h = harness();
		const p1 = h.load();
		h.pending.reject(new Error("nope"));
		await p1;
		expect(h.error.value).toBe("nope");

		const p2 = h.load();
		expect(h.error.value).toBe("");
		h.pending.resolve({ rows: [{ deal: "D1" }], currency: "UZS" });
		await p2;
		expect(h.error.value).toBe("");
		expect(h.data.value.rows).toEqual([{ deal: "D1" }]);
	});

	it("renders two different messages for the two states, not one shared EmptyState line", () => {
		// WHAT WOULD MAKE THIS FAIL: both branches rendering the same copy, which
		// is §5's exact report -- "No tenders match these filters." is wrong twice
		// over when there are no filters and the server never answered.
		//
		// P2-9 (coordinator review, 2026-09-02): the three checks below run
		// against the WHOLE footer slice, with nothing tying either sentence to
		// its OWN branch -- a mutant rendering both sentences inside one
		// `v-if="error"` div, with `v-else` deleted entirely, left this green.
		// The two more specific tests right after this one close that gap by
		// slicing each branch separately.
		const foot = src.slice(src.indexOf("filteredRows.length\""), src.indexOf("</section>"));
		expect(foot).toMatch(/v-if="error/);
		expect(foot).toMatch(/Could not load your tenders\./);
		expect(foot).toMatch(/No tenders match these filters\./);
	});

	it("the error branch carries ONLY the load-failure copy, not both sentences", () => {
		// P2-9: slices from `v-if="error` to the matching `v-else`, so a mutant
		// that merges both sentences into the v-if branch (and deletes v-else)
		// is caught here even though the whole-footer test above cannot see it.
		const foot = src.slice(src.indexOf("filteredRows.length\""), src.indexOf("</section>"));
		const errorBranch = foot.slice(foot.indexOf('v-if="error'), foot.indexOf("v-else"));
		expect(errorBranch).toMatch(/Could not load your tenders\./);
		expect(errorBranch).not.toMatch(/No tenders match these filters\./);
	});

	it("the v-else branch carries ONLY the no-match copy, not the failure sentence", () => {
		const foot = src.slice(src.indexOf("filteredRows.length\""), src.indexOf("</section>"));
		const elseBranch = foot.slice(foot.indexOf("v-else"));
		expect(elseBranch).toMatch(/No tenders match these filters\./);
		expect(elseBranch).not.toMatch(/Could not load your tenders\./);
	});

	it("load OK, then a later failure, leaves the good rows in place (P1-4)", async () => {
		// P1-4 (coordinator review, 2026-09-02) -- half of the named scenario
		// this can prove without a DOM: a good load populates rows; a LATER
		// background tick (useAutoRefresh calls load() every 60s) fails.
		// load()'s catch must not wipe data.value -- if it did, the template
		// guard added below would have nothing to distinguish a stale
		// background failure from a genuine "never loaded anything" one.
		const h = harness();
		const p1 = h.load();
		h.pending.resolve({ rows: [{ deal: "D1" }, { deal: "D2" }], currency: "UZS" });
		await p1;
		expect(h.error.value).toBe("");
		expect(h.data.value.rows.length).toBe(2);

		const p2 = h.load(); // the later, background-tick failure
		h.pending.reject(new Error("Tender module is not enabled for Mikas."));
		await p2;
		expect(h.error.value).toBe("Tender module is not enabled for Mikas.");
		expect(h.data.value.rows.length).toBe(2); // untouched by the failure
	});

	it("the empty-state guard checks for the absence of data, not only a stale error flag", () => {
		// The other half of P1-4's scenario: with real rows still in
		// data.value (proven above) and error latched from a background tick,
		// the template must not read `error` alone -- that is the exact
		// defect the review named: "good load, a tick fails, error latches
		// while the 13 rows stay on screen, the user narrows a filter to
		// nothing, and the screen says 'Could not load your tenders.' over
		// data that loaded perfectly." WHAT WOULD MAKE THIS FAIL: `v-if="error"`
		// with no rows-length condition alongside it.
		const foot = src.slice(src.indexOf("filteredRows.length\""), src.indexOf("</section>"));
		expect(foot).toMatch(/v-if="error\s*&&\s*!data\.rows\.length"/);
	});
});

describe("M14 — the table scrolls on a phone; the page does not", () => {
	// Provable without a DOM: that a scroll CONTAINER wraps the table and
	// carries `overflow-x: auto` in this file's own <style scoped>. NOT
	// provable without a DOM, and not claimed: that a phone viewport actually
	// confines the scrollbar to the table rather than the page -- that needs a
	// real browser and is outside vitest.config.mjs's `environment: "node"`.
	it("wraps <table> in its own scroll container", () => {
		const wrap = src.match(/<div class="([\w-]+)">\s*<table class="ds-table">/);
		expect(wrap, "the table is not wrapped in a dedicated div").not.toBeNull();
	});

	it("that container's own CSS rule sets overflow-x: auto", () => {
		// WHAT WOULD MAKE THIS FAIL: the wrapper div existing with no matching
		// rule (or the rule on the wrong selector) -- a div is not a scroll
		// container until CSS says so.
		const wrap = src.match(/<div class="([\w-]+)">\s*<table class="ds-table">/);
		expect(wrap).not.toBeNull();
		const style = src.match(new RegExp(`\\.${wrap[1]}\\s*\\{([^}]*)\\}`));
		expect(style, `no CSS rule for .${wrap[1]} in <style scoped>`).not.toBeNull();
		expect(style[1]).toMatch(/overflow-x:\s*auto/);
	});

	it("only .mt-scroll carries overflow-x in this file's own style block", () => {
		// P3-10 (coordinator review, 2026-09-02): the original version of this
		// test checked for `.tender-page` specifically -- a selector this file
		// never defines at all (that class belongs to TenderPage.vue) -- so the
		// regex could never match anything actually present here and always
		// passed. A mutant adding `.stbl-ds { overflow-x: auto }` to the scoped
		// block passed it too. Reworked to extract every selector in
		// <style scoped> that carries overflow-x and assert there is exactly
		// one: .mt-scroll -- so the rule being hoisted to ANY wider selector
		// (not only .tender-page specifically) is what this now catches.
		const styleBlock = src.slice(src.indexOf("<style scoped>"), src.indexOf("</style>"));
		const carriers = [...styleBlock.matchAll(/([.\w-]+)\s*\{[^}]*overflow-x[^}]*\}/g)].map((m) => m[1]);
		expect(carriers).toEqual([".mt-scroll"]);
	});

	it("gives every column a floor width the scroller can actually overflow", () => {
		// WHAT WOULD MAKE THIS FAIL: the DirectorBoard.vue mistake this was
		// measured against (coordinator, prompt 16 agent, verified in a real
		// browser). .ds-table is `width: 100%` (stabler-modernist.css:389), so a
		// bare overflow-x wrapper has nothing to overflow -- the table shrinks to
		// fit its container instead, the scroller never engages, and the two
		// tests above pass on a screen that does not scroll. DirectorBoard's own
		// `.board-scroll` wraps the identical class with zero min-width anywhere.
		// A per-column min-width is arithmetic on the declarations below, not a
		// rendered measurement -- stabler-modernist.css is shared and forbidden,
		// so the floor has to live on this screen's own <th> cells instead of
		// .ds-table itself; auto table layout takes a column's width from the
		// widest cell in it, so setting it once per header cell is enough.
		const theadRow = src.match(/<thead><tr>([\s\S]*?)<\/tr><\/thead>/);
		expect(theadRow, "table header row not found").not.toBeNull();
		const widths = [...theadRow[1].matchAll(/min-width:\s*(\d+)px/g)].map((m) => Number(m[1]));
		// Guard against vacuity (the exact trap that fired on prompt 16): a
		// regex matching nothing would let the sum below default to 0 and the
		// "> 600" check fail loudly, but a looser assertion (e.g. `.every(...)`
		// on an empty array) would pass on nothing. Assert the count directly.
		expect(widths.length, "no <th> carries a min-width -- nothing for the scroller to overflow").toBe(5);
		const total = widths.reduce((a, b) => a + b, 0);
		// Widest mainstream phone viewport in portrait is roughly 430px (iPhone
		// Pro Max); 600 leaves clear margin without pinning an exact device.
		expect(total, `column widths sum to ${total}px, not clearly wider than a phone`).toBeGreaterThan(600);
	});
});

describe("M16 (frontend half) — the landed figure a sourcing user can act on before the win", () => {
	// P1-1/P1-2 (coordinator review, 2026-09-02): the original design was a
	// switching rowLanded(r) -- `r.po_count ? r.landed : r.landed_estimate` --
	// under one "Landed" header. Two defects: (1) it contradicted §8's own
	// vocabulary ("Landed... a post-win figure. Not the quotation's pre-win
	// landed estimate") and DirectorBoard, which renders the SAME `landed`
	// field under the SAME header with no such switch, so the identical deal
	// showed two disagreeing numbers on the two screens; (2) the switch
	// triggered on the first DRAFT Purchase Order (_deal_landed_split counts
	// docstatus < 2), so an empty draft with no line items yet made `landed`
	// read 0 -- exactly the original M16 symptom, now returning the moment
	// sourcing work begins, and reading as a 73% cost drop to a user watching
	// it happen. Redesigned to never switch: `landed` renders unconditionally
	// (matches DirectorBoard, "make DirectorBoard agree" without touching it),
	// and the estimate is an always-present sub-line guarded only on its own
	// value -- the same "secondary figure lives inside the primary cell"
	// shape the Sourcing workspace's Delivered column already uses
	// (10-frontend.md, Currency display) rather than a sixth column (§4's hard
	// rule: "the five columns... are the contract").
	//
	// No pure function to lift any more -- the guard is a plain v-if in the
	// template -- so these are source-slice assertions on the Landed cell
	// specifically, anchored off the Tender cell (unique) rather than off
	// `class="ds-td-num"` (shared with the PO count cell two columns over).
	function landedCell() {
		const afterTenderCell = src.indexOf("</td>", src.indexOf("mt-tender")) + 5;
		expect(afterTenderCell, "no Tender <td> found to anchor from").toBeGreaterThan(4);
		const start = src.indexOf("<td", afterTenderCell);
		const end = src.indexOf("</td>", start) + 5;
		expect(start, "no Landed <td> found right after the Tender cell").toBeGreaterThan(-1);
		return src.slice(start, end);
	}

	it("no longer switches between the two figures under one header", () => {
		// WHAT WOULD MAKE THIS FAIL: rowLanded, or any r.po_count-keyed
		// ternary, coming back -- P1-1's defect.
		expect(src).not.toMatch(/function rowLanded/);
		expect(src).not.toMatch(/r\.po_count\s*\?/);
	});

	it("renders the post-win sum unconditionally, matching DirectorBoard's own Landed", () => {
		// WHAT WOULD MAKE THIS FAIL: hiding or replacing r.landed based on
		// po_count or landed_estimate.
		expect(landedCell()).toMatch(/\{\{\s*fm\(r\.landed\)\s*\}\}/);
	});

	it("renders the pre-win estimate as a sub-line guarded only on itself", () => {
		// WHAT WOULD MAKE THIS FAIL: gating the estimate on po_count, docstatus,
		// or anything Purchase-Order-derived -- P1-2's defect, where the first
		// EMPTY draft PO made the estimate disappear at the exact moment
		// `landed` was still 0.
		const cell = landedCell();
		expect(cell).toMatch(/v-if="r\.landed_estimate"/);
		expect(cell).toMatch(/t\("Pre-win estimate"\)/);
		expect(cell).toMatch(/fm\(r\.landed_estimate\)/);
	});

	it("keeps both figures in the same cell, beside each other, not one replacing the other", () => {
		const cell = landedCell();
		expect(cell).toMatch(/fm\(r\.landed\)/);
		expect(cell).toMatch(/fm\(r\.landed_estimate\)/);
	});
});
