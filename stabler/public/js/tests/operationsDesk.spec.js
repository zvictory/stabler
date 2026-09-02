import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { formatTime } from "../composables/date.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/OperationsDesk.vue"), "utf8");

/**
 * Three measured defects on the operations desk (docs/design/prompts/13-operations-desk.md,
 * acceptance rows D8, D12, D17), pinned so none of them comes back silently.
 *
 * Same DOM-less idiom as sourcingWorkspaceConformance.spec.js: `vitest.config.mjs`
 * runs `environment: "node"` and `@vue/test-utils` is not a dependency, so where a
 * defect is about LOGIC the expression or function is lifted out of the source text
 * and executed. A bare `toContain` on markup passes just as happily on a branch
 * wired backwards, so every logic test below evaluates the real thing — with the
 * REAL `formatTime`, not a stub, because the stamp's correctness is exactly the
 * composable's job.
 */

function anchor(marker, from = 0) {
	const at = src.indexOf(marker, from);
	expect(at, `"${marker}" marker not found — has the source moved?`).toBeGreaterThan(-1);
	return at;
}

/** Lift a single-line top-level `const NAME = ...;` out of the source. */
function liftConst(name) {
	const m = src.match(new RegExp(`^const ${name} = [\\s\\S]*?;$`, "m"));
	expect(m, `top-level const ${name} not found in OperationsDesk.vue`).not.toBeNull();
	return m[0];
}

/**
 * Lift a top-level `function name(...) { ... }` out of the source and return it as
 * a callable, preceded by any module-level consts it closes over. Relies on the
 * file's formatting convention: bodies are tab-indented, closing brace at column 0.
 *
 * Lifting the consts rather than restating their values in the test is the point:
 * the collapse order must stay derived from the severity map the bands render
 * from, and a test that hardcoded ["crit","today","soon","info"] would keep
 * passing after the source grew a second, divergent list.
 */
function liftFunction(name, deps = []) {
	const m = src.match(new RegExp(`^function ${name}\\([\\s\\S]*?^\\}`, "m"));
	expect(m, `top-level function ${name}() not found in OperationsDesk.vue`).not.toBeNull();
	const preamble = deps.map(liftConst).join("\n");
	return new Function(`${preamble}\n${m[0]}; return ${name};`)();
}

/** The right-hand side of the first `target = ...;` assignment in the source. */
function rhsOf(target) {
	const at = anchor(`${target} = `);
	const end = src.indexOf(";", at);
	return src.slice(at + `${target} = `.length, end);
}

/** Evaluate an expression against a supplied scope. */
function evalInScope(expression, scope) {
	const keys = Object.keys(scope);
	return new Function(...keys, `return (${expression});`)(...keys.map((k) => scope[k]));
}

/** Source of the lead row, opening `<button>` through its matching `</button>`. */
function leadRowBlock() {
	const at = anchor('class="ds-row ds-row--lead"');
	const open = src.lastIndexOf("<button", at);
	const close = src.indexOf("</button>", at);
	return src.slice(open, close + "</button>".length);
}

describe("D12 — the freshness stamp is the server's clock, not the browser's", () => {
	// The stamp is a computed over the stored payload (the idiom all six tender
	// screens share since 2026-09-02 — see tenderFreshness.spec.js). Running it
	// with `computed` stubbed to call its getter exercises the real expression
	// and the real formatTime, rather than pattern-matching the source.
	const stamp = (payload) =>
		evalInScope(rhsOf("const lastReadAt"), {
			computed: (fn) => fn(),
			formatTime,
			deskData: { value: payload },
		});

	it("renders the HH:mm of the payload's generated_at", () => {
		// WHAT WOULD MAKE THIS FAIL: reverting to `new Date().toTimeString().slice(0, 5)`,
		// which stamped the moment the RESPONSE ARRIVED IN THE BROWSER. That number
		// moves with the reader's device clock and timezone while the data behind it
		// does not, so two people looking at the same payload read two freshnesses.
		// `generated_at` is written by frappe.utils.now() in the site's timezone
		// (tender_desk.py:364) and is the only stamp that describes the DATA.
		expect(stamp({ generated_at: "2026-09-02 14:23:11.123456" })).toBe("14:23");
		expect(stamp({ generated_at: "2026-09-02 09:05:00" })).toBe("09:05");
	});

	it("shows nothing at all when the server sent no stamp", () => {
		// WHAT WOULD MAKE THIS FAIL: falling back to the browser clock when
		// generated_at is absent (an older server mid-deploy). That fallback is worse
		// than no stamp: it is indistinguishable from a real one and it lies. The
		// template's `v-if="lastReadAt"` means "" hides the stamp, which is the loud
		// failure — the reader sees no freshness rather than a false one.
		expect(stamp({})).toBe("");
		expect(stamp({ generated_at: null })).toBe("");
		expect(stamp({ generated_at: "" })).toBe("");
	});

	it("never reads a Date from the browser to produce the stamp", () => {
		// WHAT WOULD MAKE THIS FAIL: any reintroduction of `new Date()` into the
		// assignment — including a "helpful" `generated_at ?? new Date()` hybrid,
		// which the two tests above would not catch on the happy path.
		expect(rhsOf("const lastReadAt")).not.toMatch(/\bDate\b/);
	});
});

describe("D8 — band collapse round-trips through the URL", () => {
	// Lazily lifted: an eager call here would abort collection for the whole file
	// and hide the other two defects' verdicts behind this one's.
	const DEPS = ["SEVERITY_ORDER", "SEVERITY_TO_SEV", "COLLAPSIBLE_SEVS"];
	const fromQuery = (...a) => liftFunction("collapsedFromQuery", DEPS)(...a);
	const toQuery = (...a) => liftFunction("collapsedToQuery", DEPS)(...a);

	it("restores the collapsed bands named in ?collapsed=", () => {
		// WHAT WOULD MAKE THIS FAIL: going back to `const collapsed = ref({})`, which
		// discarded the reader's collapse on every reload, back-button and shared
		// link — while `view` and `filter` beside it survived all three. The desk is
		// a link people paste at each other; what the sender collapsed is part of
		// what they meant to point at.
		expect(fromQuery("crit,soon")).toEqual({ crit: true, soon: true });
		expect(fromQuery("info")).toEqual({ info: true });
	});

	it("treats an absent, empty or unknown value as nothing collapsed", () => {
		// WHAT WOULD MAKE THIS FAIL: trusting the query string. It is user-editable,
		// so a stray value must not create a truthy key that collapses a band no
		// severity maps to — that band would then be uncollapsible, because the only
		// control that clears the key is the band header the reader can no longer see.
		expect(fromQuery(undefined)).toEqual({});
		expect(fromQuery("")).toEqual({});
		expect(fromQuery("crit,,nonsense, soon ")).toEqual({ crit: true, soon: true });
	});

	it("writes the collapsed set back in the fixed severity order, not insertion order", () => {
		// WHAT WOULD MAKE THIS FAIL: serialising Object.keys() in insertion order.
		// Collapsing soon-then-crit and crit-then-soon are the same view, and two
		// different URLs for one view break both the back button (two entries where
		// the reader made one change) and any comparison of two shared links.
		expect(toQuery({ soon: true, crit: true })).toBe("crit,soon");
		expect(toQuery({ crit: true, soon: true })).toBe("crit,soon");
		expect(toQuery({ info: true, today: true, crit: true })).toBe("crit,today,info");
	});

	it("drops the parameter entirely when nothing is collapsed", () => {
		// WHAT WOULD MAKE THIS FAIL: emitting "" instead of undefined. `router.replace`
		// keeps an empty string as `?collapsed=` in the address bar, so the default
		// view would carry a parameter that says nothing — and the file's own idiom
		// for "omit this" is `|| undefined` (see the view key in setFilter).
		expect(toQuery({})).toBeUndefined();
		expect(toQuery({ crit: false, soon: false })).toBeUndefined();
	});

	it("round-trips: what was written back parses to the same state", () => {
		// WHAT WOULD MAKE THIS FAIL: the two halves drifting apart — a writer that
		// emits "crit soon" against a reader that splits on commas would leave the
		// URL looking right and restoring nothing.
		const state = { crit: true, info: true };
		expect(fromQuery(toQuery(state))).toEqual(state);
	});

	it("seeds the initial state from the URL rather than from an empty object", () => {
		// WHAT WOULD MAKE THIS FAIL: `const collapsed = ref({})` — today's bug. Every
		// pure-function test above would still pass with it, because the encoder and
		// decoder would be present and correct and simply never consulted on load.
		// This is the assertion that makes reverting the ref visible.
		const init = rhsOf("const collapsed");
		expect(init).toMatch(/collapsedFromQuery\(/);
		expect(init).toMatch(/route\.query\.collapsed/);
	});

	it("follows the back button, the way the filter already does", () => {
		// WHAT WOULD MAKE THIS FAIL: omitting the watcher. The URL would then be
		// written on every toggle and read only on a full page load, so going Back
		// after collapsing a band would change the address bar and not the screen —
		// which is worse than not being in the URL at all.
		const at = anchor("() => route.query.collapsed");
		const body = src.slice(src.lastIndexOf("watch(", at), src.indexOf(");", at));
		expect(body).toMatch(/collapsed\.value = collapsedFromQuery\(/);
	});

	it("keeps the toggle writing through router.replace, beside view and filter", () => {
		// WHAT WOULD MAKE THIS FAIL: the helpers existing but nothing calling them —
		// the pure functions above would still pass while the URL never changed.
		const body = src.slice(anchor("function toggleGroup("), anchor("function setFilter("));
		expect(body).toMatch(/router\.replace/);
		expect(body).toMatch(/collapsed: collapsedToQuery\(/);
	});
});

describe("D17 — the lead row's call to action is the control, not a painted span", () => {
	it("draws no ds-btn inside the lead row", () => {
		// WHAT WOULD MAKE THIS FAIL: restoring `<span class="ds-btn ds-btn--primary">`.
		// The row itself is the <button>; a span painted as a primary button inside it
		// is a target that cannot be focused, cannot be tabbed to and cannot be the
		// thing a screen reader announces — while looking like the one control on the
		// most important row of the screen. (It is also a control nested in a control,
		// which is why the answer is to unpaint the span, not to promote it.)
		expect(leadRowBlock()).not.toMatch(/ds-btn/);
	});

	it("keeps the lead row itself the focusable control that opens the item", () => {
		// WHAT WOULD MAKE THIS FAIL: unpainting the span by demoting the row to a
		// <div> — that would remove the fake control by removing the real one too.
		const block = leadRowBlock();
		expect(block.startsWith("<button")).toBe(true);
		expect(block).toMatch(/type="button"/);
		expect(block).toMatch(/@click="openItem\(leadItem\)"/);
	});

	it("carries exactly one control for the lead item — no nested button", () => {
		// WHAT WOULD MAKE THIS FAIL: turning the CTA into a real <button> inside the
		// row. Nested buttons are invalid HTML; browsers recover differently and the
		// inner one swallows the row's own click on some of them.
		expect(leadRowBlock().match(/<button/g)).toHaveLength(1);
	});

	it("still tells the reader the row opens something", () => {
		// WHAT WOULD MAKE THIS FAIL: deleting the affordance along with the paint.
		// The row is a control; removing every visible sign of that is the opposite
		// fix. The verb and the arrow stay — only the button costume goes.
		const block = leadRowBlock();
		expect(block).toMatch(/t\("Open"\)/);
		expect(block).toMatch(/→/);
	});

	it("adds no third child to the lead row's two-column grid", () => {
		// WHAT WOULD MAKE THIS FAIL: unpainting the span by moving the affordance
		// out into its own element beside the body and the right column. The layer
		// gives .ds-row--lead `grid-template-columns: 1fr auto`
		// (stabler-modernist.css:329) — two columns, because the lead row has
		// neither a severity cell nor the ordinary rows' chevron. A third grid item
		// wraps onto a new row under the title, and the only way to keep it in line
		// is for this page to override the layer's own grid.
		const children = leadRowBlock().match(/^\t{6}<(?!\/)/gm) ?? [];
		expect(children).toHaveLength(2);
	});
});
