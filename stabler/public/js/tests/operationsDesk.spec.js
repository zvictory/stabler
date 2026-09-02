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
function liftFunction(name, deps = [], scope = {}) {
	const m = src.match(new RegExp(`^function ${name}\\([\\s\\S]*?^\\}`, "m"));
	expect(m, `top-level function ${name}() not found in OperationsDesk.vue`).not.toBeNull();
	const preamble = deps.map(liftConst).join("\n");
	const keys = Object.keys(scope);
	return new Function(
		...keys,
		`${preamble}\n${m[0]}; return ${name};`
	)(...keys.map((k) => scope[k]));
}

/** The right-hand side of the first `target = ...;` assignment in the source. */
function rhsOf(target) {
	const at = anchor(`${target} = `);
	const end = src.indexOf(";", at);
	return src.slice(at + `${target} = `.length, end);
}

/**
 * The right-hand side of a MULTI-LINE `const NAME = computed(() => { … });`.
 * `rhsOf` cannot be used for these: it stops at the first `;`, which inside a
 * block body is a statement terminator, not the end of the declaration.
 */
function blockRhsOf(name) {
	const m = src.match(new RegExp(`^const ${name} = ([\\s\\S]*?^\\}\\));$`, "m"));
	expect(m, `multi-line const ${name} not found in OperationsDesk.vue`).not.toBeNull();
	return m[1];
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

/**
 * The plan panel's state chain: the loading branch through the last state branch
 * before rows are drawn. Anchored on `:rows="6"` — the plan skeleton's own row
 * count — because `SkeletonRows` appears twice in the file and an anchor on the
 * component name alone would slice the decision box's chain instead.
 */
function planStateChain() {
	const from = anchor('<SkeletonRows v-if="loading" :rows="6"');
	return src.slice(from, anchor("<template v-else>", from));
}

/** The `v-if`/`v-else-if` conditions of a branch chain, in source order. */
function branchConditions(block) {
	return [...block.matchAll(/v-(?:else-)?if="([^"]+)"/g)].map((m) => m[1]);
}

/** Everything between `<template>` and `<script setup>` — the rendered markup. */
const template = src.slice(src.indexOf("<template>"), src.indexOf("<script setup>"));

/** Every `{{ … }}` interpolation in the template: what the reader actually sees. */
function interpolations() {
	return [...template.matchAll(/\{\{[^}]*\}\}/g)].map((m) => m[0]);
}

/**
 * The `<script setup>` block with its comments dropped, so counting call sites
 * counts CODE. Every comment in OperationsDesk.vue sits on its own line — the
 * block ones open the line and continue it with an asterisk, the line ones start
 * at the indent — so dropping whole comment lines is exact here and does not need
 * a parser that would also have to understand strings and regex literals.
 */
function scriptWithoutComments() {
	return src
		.slice(src.indexOf("<script setup>"), src.indexOf("</script>"))
		.split("\n")
		.filter((line) => !/^\s*(\/\/|\/\*|\*)/.test(line))
		.join("\n");
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

describe("D9 — a view the reader lacks is forbidden, not an error", () => {
	const isForbidden = (...a) => liftFunction("isForbidden")(...a);

	it("reads the server's 403 as a refusal", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping the status check. Gate 3 is the only
		// one of this screen's three gates that lives on the server —
		// `_require_tender_view` throws frappe.PermissionError (tender.py:1893),
		// Frappe answers 403, and client.js:73 puts that on `err.status`. Without
		// this read the refusal lands in `error` and a person who typed a view they
		// do not hold is told the desk broke, which sends them to support instead of
		// to whoever grants roles.
		//
		// The message here is the Uzbek for "not permitted" on purpose: `_()` is
		// translated server-side, so on three of the four shipped languages the
		// wording half of the check matches nothing. Asserting with the English
		// text would let a status-blind implementation pass this test and fail in
		// production for most of the users.
		expect(isForbidden({ status: 403, message: "Ruxsat berilmagan" })).toBe(true);
	});

	it("does not read an ordinary failure as a refusal", () => {
		// WHAT WOULD MAKE THIS FAIL: widening the test to any error. The two states
		// have opposite recoveries — a refusal is answered by asking for a role, a
		// failure by retrying — so calling a 500 "forbidden" is exactly as wrong as
		// calling a 403 "error", and it hides real breakage behind a policy message.
		expect(isForbidden({ status: 500, message: "Internal Server Error" })).toBe(false);
		expect(isForbidden({ message: "Failed to fetch" })).toBe(false);
		expect(isForbidden(undefined)).toBe(false);
	});

	it("matches the refusal wording Frappe actually sends, not just the word 'permission'", () => {
		// WHAT WOULD MAKE THIS FAIL: copying the repo's other five call sites
		// verbatim — `/role|permission/i` (UnbilledReceipts.vue:235). Measured: the
		// throw on this path is _("Not permitted") (tender.py:1893), and "permitted"
		// does not contain "permission", so that regex matches nothing here. The
		// status code is the load-bearing half; this fallback only has to stop being
		// decorative.
		expect(isForbidden({ message: "Not permitted" })).toBe(true);
	});

	it("clears the refusal at the start of every fetch, the way the error is cleared", () => {
		// WHAT WOULD MAKE THIS FAIL: setting `forbidden` and never resetting it. The
		// picker calls fetchDesk() on change, so one refused view would leave the
		// desk refusing forever — including for the views the reader does hold.
		const body = src.slice(anchor("async function fetchDesk("), anchor("const filteredPlan"));
		expect(body).toMatch(/error\.value = "";/);
		expect(body).toMatch(/forbidden\.value = false;/);
	});

	it("routes a refusal to `forbidden` and leaves `error` empty", () => {
		// WHAT WOULD MAKE THIS FAIL: setting both. The template renders the first
		// matching branch, so setting both would still look right today and would
		// break silently the moment the branches are reordered — and any reader of
		// the state would see a screen claiming to be broken AND refused at once.
		const at = anchor("} catch (err) {");
		const body = src.slice(at, src.indexOf("} finally {", at));
		expect(body).toMatch(/if \(isForbidden\(err\)\) \{[\s\S]*?forbidden\.value = true;/);
		expect(body).toMatch(/\n\t\t} else \{/);
	});

	it("draws the refusal as its own branch, ahead of the error branch", () => {
		// WHAT WOULD MAKE THIS FAIL: rendering the refusal through `error`. The
		// module and company gates already get their own worded branches; this is
		// the third gate, and collapsing it into the red one throws away the
		// distinction the other two exist to protect. Order matters because an error
		// branch placed first would swallow the refusal on any future change that
		// sets both.
		const conditions = branchConditions(planStateChain());
		expect(conditions).toContain("forbidden");
		expect(conditions.indexOf("forbidden")).toBeLessThan(conditions.indexOf("error"));
	});

	it("does not announce the refusal as an alert", () => {
		// WHAT WOULD MAKE THIS FAIL: copying role="alert" onto the refusal branch.
		// `role="alert"` is an assertive live region — it interrupts a screen reader
		// because something went wrong. A view you were never entitled to open is a
		// policy outcome, not a failure, and it is announced the way the other two
		// gates are, which carry no role at all.
		const chain = planStateChain();
		expect(chain).toContain('v-else-if="forbidden"');
		const branch = chain.slice(chain.indexOf('v-else-if="forbidden"'));
		expect(branch.slice(0, branch.indexOf(">"))).not.toMatch(/role="alert"/);
		expect(chain).toMatch(/v-else-if="error"[^>]*role="alert"/);
	});

	it("hides the counter strip while the view is refused", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving the four chips drawn. With no payload
		// they render 0 / 0 / 0 / 0 under their rules ("due date passed, still
		// open"), which reads as "nothing is overdue" — a measurement of a view the
		// server just declined to measure. Four confident zeros beside a refusal is
		// worse than either state alone.
		const at = anchor('class="ds-kpis" data-cols="4"');
		const tag = src.slice(src.lastIndexOf("<div", at), src.indexOf(">", at));
		expect(tag).toMatch(/v-if="!forbidden"/);
	});
});

describe("D10 — the rule's internal name never reaches the reader", () => {
	const stubT = { t: (key) => key };
	const kindLabel = (...a) => liftFunction("kindLabel", ["KIND_LABEL"], stubT)(...a);

	// The eight kinds `_desk_rules.build_plan` can emit. Restated here rather than
	// scraped because a JS test cannot import Python; the two lists are held equal
	// by test_operations_desk_source.py, which reads _desk_rules.py directly. If
	// that pairing is ever broken, THAT test is the one that says so.
	const KINDS = [
		"bid_due",
		"bid_soon",
		"policy_gap",
		"no_parent",
		"won_no_po",
		"po_late",
		"invoice_due",
		"approval_pending",
	];

	it("gives every rule a sentence a person would say out loud", () => {
		// WHAT WOULD MAKE THIS FAIL: labelling some kinds and leaving the rest to
		// fall through. The evidence line sits on the most prominent row of a screen
		// whose whole promise is that the reader will not have to ask anyone what it
		// means; `won_no_po` is the machine asking the reader to ask someone.
		for (const kind of KINDS) {
			expect(kindLabel(kind), kind).toMatch(/^[A-Z][A-Za-z ,]+$/);
		}
	});

	it("keeps the eight labels distinct", () => {
		// WHAT WOULD MAKE THIS FAIL: giving bid_due and bid_soon one label. They are
		// different rules with different severities — "deadline passed" and "deadline
		// in two days" — and one word for both makes the evidence line decorative:
		// the reader still cannot tell which query produced the row.
		const labels = KINDS.map(kindLabel);
		expect(new Set(labels).size).toBe(KINDS.length);
	});

	it("renders nothing at all for a kind it does not know", () => {
		// WHAT WOULD MAKE THIS FAIL: a `|| kind` fallback. That is the leak coming
		// straight back the first time the server grows a ninth rule — and the
		// evidence line is optional (`v-if`), so dropping it costs a line while
		// printing `shipment_stuck` costs the screen's credibility. The loud failure
		// belongs in CI, where test_operations_desk_source.py compares the map
		// against _desk_rules.py.
		expect(kindLabel("shipment_stuck")).toBe("");
		expect(kindLabel(undefined)).toBe("");
	});

	it("never interpolates a raw `kind` in the template", () => {
		// WHAT WOULD MAKE THIS FAIL: reverting either call site — or adding a third.
		// Measured 2026-09-02: there were TWO, not the one S3 lists. The lead row
		// printed `bid_due` once; the band rows printed `bid_due`, `policy_gap` and
		// `bid_soon` on every other row of the seed's four. Anchoring on the shape of
		// the leak instead of on two line numbers is what makes a third one fail.
		const leaks = interpolations().filter((x) => /\.kind\b/.test(x) && !/kindLabel\(/.test(x));
		expect(leaks).toEqual([]);
	});
});

describe("D11 — the role picker shows a name, not the id behind it", () => {
	const stubT = { t: (key) => key };
	const viewLabel = (...a) => liftFunction("viewLabel", ["VIEW_LABEL"], stubT)(...a);

	// The four view ids _TENDER_VIEW_ROLES defines (tender.py:1863). Same pairing
	// note as KINDS above: test_operations_desk_source.py holds this equal to the
	// Python.
	const VIEWS = ["sourcing", "declarant", "logist", "director"];

	it("names all four role views", () => {
		// WHAT WOULD MAKE THIS FAIL: going back to `t(v.label || v.id)`. The server
		// built `{"id": v, "label": v}` — the label WAS the id — so the option text
		// was `logist`, and t() returned it unchanged because none of the four ids is
		// a key in any catalogue (measured: en.csv has `Sourcing` and `Declarant`,
		// capitalised, and neither `logist` nor `director` in any case).
		for (const view of VIEWS) {
			expect(viewLabel(view), view).toMatch(/^[A-Z][A-Za-z]+$/);
		}
	});

	it("does not print `logist` under a different name", () => {
		// WHAT WOULD MAKE THIS FAIL: mapping an id to itself to satisfy the shape
		// test above — `logist: t("logist")` passes nothing and looks like a fix.
		for (const view of VIEWS) {
			expect(viewLabel(view)).not.toBe(view);
		}
	});

	it("falls back to the id for a view it does not know", () => {
		// WHAT WOULD MAKE THIS FAIL: returning "" here, the way kindLabel does. The
		// two are not the same case: the evidence line is optional and vanishes, but
		// an <option> with empty text is a blank row in a picker — a view the reader
		// can select and cannot name is worse than one named badly. A fifth view
		// added server-side fails test_operations_desk_source.py, which is where a
		// missing label should be reported.
		expect(viewLabel("procurement")).toBe("procurement");
		expect(viewLabel(undefined)).toBe("");
	});

	it("routes both view renderings through the label map", () => {
		// WHAT WOULD MAKE THIS FAIL: fixing the picker and leaving the meta row, or
		// the reverse. They are two different mechanisms with one result — the
		// machine's vocabulary in front of a human — and the header line is the one
		// a reader sees without opening anything.
		const leaks = interpolations().filter(
			(x) => /\bdeskData\.view\b|\bv\.(id|label)\b/.test(x) && !/viewLabel\(/.test(x)
		);
		expect(leaks).toEqual([]);
	});
});

describe("D18 — the reader can tell which clock said 'today'", () => {
	// Same idiom as D12: run the real computeds with `computed` stubbed to call its
	// getter, so the expressions are exercised rather than pattern-matched.
	const evalWith = (expression, payload, browser = "2026-09-02") =>
		evalInScope(expression, {
			computed: (fn) => fn(),
			deskData: { value: payload },
			browserToday: browser,
			serverToday: { value: payload?.today || "" },
			t: (key) => key,
		});

	const today = (payload, browser) => evalWith(rhsOf("const todayStr"), payload, browser);
	const clockLabel = (payload, browser) => evalWith(rhsOf("const todayClockLabel"), payload, browser);
	const skew = (payload, browser) => evalWith(rhsOf("const clockSkew"), payload, browser);

	it("counts with the server's calendar day, not the browser's", () => {
		// WHAT WOULD MAKE THIS FAIL: going back to `const todayStr = todayIso()`.
		// The server derives every severity and every counter from
		// frappe.utils.today() in the site's timezone (tender_desk.py:48); the
		// client re-filtered the SAME predicate with the browser's date. Identical
		// predicate, different clock — so on a night when the two disagree the Today
		// chip reads 2 and the list it filters to shows 1, and each half is
		// internally consistent. On a Tashkent site read from a Tashkent browser
		// they always agree, which is exactly why nobody would catch the day they
		// do not.
		expect(today({ today: "2026-09-03" }, "2026-09-02")).toBe("2026-09-03");
	});

	it("falls back to the device only when the server sent no date", () => {
		// WHAT WOULD MAKE THIS FAIL: hard-failing (a blank header and a TODAY badge
		// that never fires) when the key is absent — which is every request against
		// a server deployed before this change, and every render before the first
		// response lands.
		expect(today({}, "2026-09-02")).toBe("2026-09-02");
		expect(today(null, "2026-09-02")).toBe("2026-09-02");
	});

	it("names the clock it used, in both cases", () => {
		// WHAT WOULD MAKE THIS FAIL: silently switching to the server's date. That
		// closes the seam and leaves the acceptance row open: the reader still
		// cannot tell which clock produced the word "today". The fallback especially
		// has to say so — an unlabelled device date is indistinguishable from a
		// server one and is the exact state this screen was in.
		expect(clockLabel({ today: "2026-09-03" })).toBe("server date");
		expect(clockLabel({})).toBe("device date");
	});

	it("flags a disagreement only when there is one to flag", () => {
		// WHAT WOULD MAKE THIS FAIL: raising the flag whenever the server date is
		// missing. On the ordinary day — a Tashkent site read from Tashkent — the
		// two dates match and a permanent warning is noise that trains the reader to
		// ignore the one night it matters.
		expect(skew({ today: "2026-09-03" }, "2026-09-02")).toBe(true);
		expect(skew({ today: "2026-09-02" }, "2026-09-02")).toBe(false);
		expect(skew({}, "2026-09-02")).toBe(false);
	});

	it("reads the browser's calendar date exactly once", () => {
		// WHAT WOULD MAKE THIS FAIL: a second `todayIso()` call left behind at one
		// of the four sites todayStr drives (header, TODAY filter, calendar today
		// cell, row badge). Two sources of "today" in one screen is the defect this
		// row exists to close, and the second one would agree on every day a test
		// is likely to be run. Comments are stripped first: this file's own comment
		// above the fallback names `todayIso()` while explaining the UTC bug it was
		// added for, and a test that counted that would be counting prose.
		expect(scriptWithoutComments().match(/todayIso\(\)/g)).toHaveLength(1);
	});

	it("puts the clock's name and the disagreement in the meta row", () => {
		// WHAT WOULD MAKE THIS FAIL: computing all of it and rendering none of it.
		// The meta row is the module's only freshness surface; a state that exists
		// only in the script is a state the reader does not have.
		const meta = src.slice(anchor("<template #meta>"), anchor("<template #actions>"));
		expect(meta).toMatch(/\{\{ todayClockLabel \}\}/);
		expect(meta).toMatch(/v-if="clockSkew"/);
		expect(meta).toMatch(/browserToday/);
	});
});

describe("D13 — an overdue item is discoverable from the calendar region", () => {
	// The calendar panel: its heading through the end of the section.
	const calendarPanel = () => {
		const at = anchor('<h3>{{ t("Next 7 days") }}</h3>');
		return src.slice(at, anchor("</section>", at));
	};

	const bucket = (payload) =>
		evalInScope(blockRhsOf("pastDue"), { computed: (fn) => fn(), deskData: { value: payload } });

	it("reads the count the server partitioned, and does not re-derive it", () => {
		// WHAT WOULD MAKE THIS FAIL: counting overdue rows on the client instead.
		// The plan the client holds is already filtered by the chip, so a client
		// count would fall to 0 the moment the reader pressed Today — the calendar
		// would then say "nothing is past due" because of a filter, which is the
		// hard rule this screen states outright: severity is derived server-side and
		// the client groups it, never re-decides it.
		expect(bucket({ calendar_past: { count: 3, items: [] } }).count).toBe(3);
		expect(blockRhsOf("pastDue")).toMatch(/calendar_past/);
		expect(blockRhsOf("pastDue")).not.toMatch(/filteredPlan|severity/);
	});

	it("names the past-due items in the same tooltip the day cells use", () => {
		// WHAT WOULD MAKE THIS FAIL: a bare count. The seven cells carry up to two
		// titles in `title` — the only place those titles appear anywhere on this
		// screen — and a bucket that says "3" without saying which three is a worse
		// version of the region that said nothing at all.
		const b = bucket({ calendar_past: { count: 2, items: [{ title: "Bid due: A" }, { title: "Late: B" }] } });
		expect(b.tooltip).toBe("Bid due: A\nLate: B");
	});

	it("survives a server that does not send the bucket", () => {
		// WHAT WOULD MAKE THIS FAIL: reading .count off undefined. An older server
		// mid-deploy would blank the whole desk rather than the one new cell.
		expect(bucket({}).count).toBe(0);
		expect(bucket(null).tooltip).toBe("");
	});

	it("draws the bucket inside the calendar panel", () => {
		// WHAT WOULD MAKE THIS FAIL: putting it anywhere else. The acceptance row is
		// specifically that the overdue item is discoverable FROM THE CALENDAR
		// REGION — the region a reader scans to plan a week, and the one that could
		// not agree with the Overdue chip directly above it.
		//
		// The count itself, not merely the name: an earlier draft asserted
		// /pastDue\.count/ and passed against a bucket stripped down to its label,
		// because the `:data-sev` binding mentions the count too. A bucket that
		// says "PAST DUE" and no number is the region saying nothing again.
		expect(calendarPanel()).toMatch(/\{\{ pastDue\.count/);
	});

	it("does not put an eighth cell in a seven-column grid", () => {
		// WHAT WOULD MAKE THIS FAIL: adding the bucket as another .ds-week-day. The
		// layer gives .ds-week `grid-template-columns: repeat(7, minmax(0,1fr))`
		// (stabler-modernist.css:361), so an eighth child wraps onto a second row as
		// a lone cell — and it would be claiming to be a day, which is the one thing
		// the bucket is not.
		const cells = [...calendarPanel().matchAll(/<div[^>]*class="ds-week-day"[^>]*>/g)];
		expect(cells).toHaveLength(1);
		expect(cells[0][0]).toMatch(/v-for="day in week"/);
	});

	it("takes its colour from the layer, not from this page", () => {
		// WHAT WOULD MAKE THIS FAIL: styling the bucket red in the scoped block.
		// The file's own rule is that colour, type, border and spacing all come from
		// stabler-modernist.css; `data-sev="crit"` on any ancestor already turns
		// .ds-sev red (:307-308), so the bucket needs no rule of its own.
		expect(calendarPanel()).toMatch(/:data-sev="pastDue\.count \? 'crit' : null"/);
		const style = src.slice(anchor("<style scoped>"));
		expect(style).not.toMatch(/desk-week-past/);
	});
});
