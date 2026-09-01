import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/SourcingWorkspace.vue"), "utf8");

/**
 * Five measured defects in SourcingWorkspace.vue, pinned so none of them comes
 * back silently.
 *
 * Same idiom as sourcingAwardPanel.spec.js: DOM-less, no `mount()` —
 * `vitest.config.mjs` runs `environment: "node"` and `@vue/test-utils` is not
 * a dependency here. Where a defect is about LOGIC (what a template
 * expression actually evaluates to for a given ref state), the expression is
 * extracted from the source text and executed via `evalInScope` — a
 * `toContain` on the raw markup passes just as happily on a branch wired
 * backwards. Where a defect is genuinely about an attribute being present or
 * a forbidden class being absent (defects 2, 4, 5), a source-text assertion
 * IS the established idiom (see fieldErrorReachesTheControl.spec.js) — but
 * every one below is a counted regression guard, not a bare `toContain`, and
 * each test's own comment says what would have to change in the behaviour
 * for it to fail.
 */

function anchor(marker, from = 0) {
	const at = src.indexOf(marker, from);
	expect(at, `"${marker}" marker not found — has the markup moved?`).toBeGreaterThan(-1);
	return at;
}

/** Evaluate a template expression against a supplied render scope. */
function evalInScope(expression, scope) {
	const keys = Object.keys(scope);
	return new Function(...keys, `return (${expression});`)(...keys.map((k) => scope[k]));
}

/** Replace every `{{ expr }}` in a template snippet with its evaluated, stringified value. */
function renderMustaches(templateSnippet, scope) {
	return templateSnippet.replace(/\{\{([\s\S]*?)\}\}/g, (_, expr) =>
		String(evalInScope(expr.trim(), scope)),
	);
}

/** Inner content of the first `<span …classHint…>…</span` at or after `marker`. */
function spanInnerAfter(marker, classHint) {
	const classAt = anchor(classHint, anchor(marker));
	const openEnd = src.indexOf(">", classAt) + 1;
	const closeAt = src.indexOf("</span", openEnd);
	return src.slice(openEnd, closeAt);
}

/** Content between the opening tag that carries `marker` and the given closing tag. */
function tagBodyAfter(marker, closeTag) {
	const tagClose = src.indexOf(">", anchor(marker));
	const bodyEnd = src.indexOf(closeTag, tagClose);
	return src.slice(tagClose + 1, bodyEnd);
}

/** The first `{{ expr }}` found in a snippet, trimmed. */
function firstMustache(snippet) {
	const m = snippet.match(/\{\{([\s\S]*?)\}\}/);
	expect(m, "no {{ }} mustache found in the given snippet").not.toBeNull();
	return m[1].trim();
}

describe("defect 1 — RFQ count badge does not pair a bare number against a plural noun", () => {
	const badge = () =>
		spanInnerAfter("Requests for Quotation (RFQ)", "bg-secondary-lt text-secondary");
	const render = (n) => renderMustaches(badge(), { t: (s) => s, rfqs: { length: n } });

	it('never renders the literal "1 RFQs" that a native reader parses as wrong', () => {
		// WHAT WOULD MAKE THIS FAIL: reverting the badge to
		// `{{ rfqs.length }} {{ t("RFQs") }}` (or any wording that puts a bare
		// count directly beside the plural noun) — with exactly one RFQ that
		// reads "1 RFQs", and the i18n layer has no plural rule to fix it with.
		expect(render(1)).not.toBe("1 RFQs");
		expect(render(1)).not.toMatch(/^1\s+RFQs\b/);
	});

	it("keeps the label text identical regardless of count — a rewording, not a hidden plural branch", () => {
		// WHAT WOULD MAKE THIS FAIL: swapping in a `count === 1 ? "RFQ" : "RFQs"`
		// style branch (an `(s)` workaround by another name) would make the two
		// renders differ by more than the digit itself.
		const one = render(1).replace(/\d+/, "#");
		const five = render(5).replace(/\d+/, "#");
		expect(one).toBe(five);
	});
});

describe("defect 2 — every alert-warning/alert-danger banner announces itself to assistive tech", () => {
	function alertTags() {
		const re = /class="alert alert-(?:warning|danger)[^"]*"/g;
		const tags = [];
		let m;
		while ((m = re.exec(src))) {
			tags.push(src.slice(m.index, src.indexOf(">", m.index)));
		}
		return tags;
	}

	it("still has (at least) the four banners this fix touches", () => {
		// WHAT WOULD MAKE THIS FAIL: deleting one of the four banners this fix
		// covers without also removing its guard here — a silent scope cut.
		expect(alertTags().length).toBeGreaterThanOrEqual(4);
	});

	it('carries role="alert" on every one of them, not just somewhere in the file', () => {
		// WHAT WOULD MAKE THIS FAIL: dropping role="alert" from any one of the
		// four banner tags, or adding a fifth alert-warning/alert-danger banner
		// without it. Checking co-location (not a bare file-wide count) is the
		// point — four role="alert" attributes floating on unrelated elements
		// would satisfy a naive count and say nothing about these banners.
		const missing = alertTags().filter((tag) => !/role="alert"/.test(tag));
		expect(missing).toEqual([]);
	});
});

describe("defect 3 — SkeletonRows never nests inside a real <tbody>", () => {
	// SkeletonRows.vue's own root IS a <tbody> (SkeletonRows.vue:10), so putting
	// it inside another <tbody> renders <tbody><tbody>…</tbody></tbody>. Vue
	// requires v-else to be the element's IMMEDIATE next sibling, so asserting
	// this adjacency in the source text also proves the two are siblings under
	// <table>, not one nested inside the other.
	it("sits as a sibling of <tbody v-else>, in both comparison tables", () => {
		// WHAT WOULD MAKE THIS FAIL: putting <SkeletonRows> back as a child of an
		// unconditional <tbody> that also holds the v-for rows.
		const matches = src.match(/<SkeletonRows\b[^>]*\/>\s*<tbody v-else/g) ?? [];
		expect(matches.length).toBe(2);
	});

	it("keeps each SkeletonRows wired to its own loading flag and column/row counts", () => {
		// WHAT WOULD MAKE THIS FAIL: the sibling-tbody refactor accidentally
		// dropping or swapping a v-if condition or a :cols/:rows prop.
		const tags = src.match(/<SkeletonRows\b[^>]*\/>/g) ?? [];
		expect(tags.length).toBe(2);
		expect(tags[0]).toMatch(/v-if="loading"/);
		expect(tags[0]).toMatch(/:cols="9"/);
		expect(tags[0]).toMatch(/:rows="4"/);
		expect(tags[1]).toMatch(/v-if="unassignedLoading"/);
		expect(tags[1]).toMatch(/:cols="7"/);
		expect(tags[1]).toMatch(/:rows="2"/);
	});
});

describe("defect 4 — policy exception toggle uses the plain checkbox the design layer allows", () => {
	it("never renders form-switch, anywhere in this file", () => {
		// WHAT WOULD MAKE THIS FAIL: restoring `form-switch` to the
		// policy-exception wrapper, or adding it to any other form-check here.
		expect(src).not.toMatch(/form-switch/);
	});

	it("keeps the same input wired to the same v-model under the plain form-check", () => {
		// WHAT WOULD MAKE THIS FAIL: the class fix collaterally touching the
		// binding, id, or input type — the task allows only the class to change.
		const at = anchor('class="form-check mb-2"');
		const chunk = src.slice(at, src.indexOf("</div>", at));
		expect(chunk).toMatch(/id="policy-exception-chk"/);
		expect(chunk).toMatch(/v-model="awardForm\.policy_exception"/);
		expect(chunk).toMatch(/type="checkbox"/);
	});
});

describe("defect 5 — Save/Approve buttons signal busy state through their label, not a spinner glyph", () => {
	it("renders zero spinner-border glyphs", () => {
		// WHAT WOULD MAKE THIS FAIL: reintroducing spinner-border on either button.
		expect(src).not.toMatch(/spinner-border/);
	});

	it("binds aria-busy on both buttons to the ref that actually flips while the request is in flight", () => {
		// WHAT WOULD MAKE THIS FAIL: removing :aria-busy from either button, or
		// wiring it to a different ref (e.g. the form-validity computed instead
		// of the request's own busy flag) — that would announce "busy" while the
		// user is simply mid-filling the form and no request is in flight.
		expect(src).toMatch(/:aria-busy="savingDecision"/);
		expect(src).toMatch(/:aria-busy="approvingDecision"/);
	});

	it('swaps the Save button label to "Saving…" only while savingDecision is true', () => {
		const expr = firstMustache(tagBodyAfter('@click="saveDecision"', "</button>"));
		const render = (savingDecision, hasDecision) =>
			evalInScope(expr, {
				t: (s) => s,
				savingDecision,
				decisionData: hasDecision ? { decision: {} } : null,
			});

		// WHAT WOULD MAKE THIS FAIL: the label staying a static
		// `decisionData?.decision ? … : …` ternary that never reads
		// savingDecision at all (today's bug — the spinner was the only busy
		// signal, and it carried no text for assistive tech).
		expect(render(true, false)).toBe("Saving…");
		expect(render(true, true)).toBe("Saving…");
		expect(render(false, false)).toBe("Save draft decision");
		expect(render(false, true)).toBe("Update draft decision");
	});

	it('swaps the Approve button label to "Approving…" only while approvingDecision is true', () => {
		const expr = firstMustache(tagBodyAfter('@click="approveDecision"', "</button>"));
		const render = (approvingDecision) => evalInScope(expr, { t: (s) => s, approvingDecision });

		// WHAT WOULD MAKE THIS FAIL: the label staying the static
		// `t("Approve decision")` it is today, with busy conveyed only by the
		// (now removed) spinner glyph.
		expect(render(true)).toBe("Approving…");
		expect(render(false)).toBe("Approve decision");
	});
});
