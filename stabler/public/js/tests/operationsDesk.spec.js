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
 * Offset of the `<template v-else>` that draws the ROWS — the one at four tabs,
 * which closes the plan panel's state chain. The empty branch nests a
 * `<template v-else>` of its own at five tabs, so a plain
 * `indexOf("<template v-else>")` stops inside the empty state instead of after
 * it. A newline plus exactly four tabs is what tells the two apart.
 */
function rowsTemplate() {
	return anchor("\n\t\t\t\t<template v-else>");
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

/**
 * `regionStateText` executed against a supplied state. Module scope because two
 * describes need it: the refusal's wording is a D9 fact and a D15 fact at once.
 */
function regionText(state, over = {}) {
	return new Function(
		"computed",
		"t",
		"regionState",
		"error",
		"forbiddenMessage",
		`${liftConst("REGION_STATE_TEXT")}\nreturn (${blockRhsOf("regionStateText")});`
	)(
		(fn) => fn(),
		(key) => key,
		{ value: state },
		{ value: over.error || "" },
		{ value: over.forbiddenMessage || "" }
	);
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
		const body = src.slice(anchor("async function fetchDesk("), anchor("const regionState"));
		expect(body).toMatch(/error\.value = "";/);
		expect(body).toMatch(/forbidden\.value = false;/);
		// The two facts that describe the refusal have to be cleared with it, or the
		// next refusal inherits the previous one's sentence and recovery advice.
		expect(body).toMatch(/forbiddenMessage\.value = "";/);
		expect(body).toMatch(/forbiddenView\.value = "";/);
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

	it("does not announce the refusal as an alert, in any region", () => {
		// WHAT WOULD MAKE THIS FAIL: announcing every gate. `role="alert"` is an
		// assertive live region — it interrupts a screen reader because something
		// went wrong. A desk you were never entitled to open is a policy outcome,
		// not a failure, and four regions interrupting at once over one policy
		// outcome is four interruptions for no news.
		//
		// The binding is READ FROM EACH PANEL and then evaluated. An earlier version
		// of this test evaluated the ternary as a literal typed into the test, so it
		// proved the ternary correct and the SOURCE not at all: hardcoding
		// role="alert" back into a panel killed nothing. A test that cannot see the
		// file it is about is decoration.
		for (const [heading, block] of Object.entries(regionPanels())) {
			const binding = block.match(/:role="([^"]+)"/);
			expect(binding, `${heading}: gate branch has no :role binding`).not.toBeNull();
			expect(block, `${heading}: a hardcoded role="alert" is back`).not.toMatch(
				/\srole="alert"/
			);
			const role = (state) => evalInScope(binding[1], { regionState: state });
			expect(role("forbidden"), heading).toBeNull();
			expect(role("module"), heading).toBeNull();
			expect(role("company"), heading).toBeNull();
			expect(role("error"), heading).toBe("alert");
		}
	});

	it("keeps the server's own sentence for a refusal", () => {
		// WHAT WOULD MAKE THIS FAIL: throwing err.message away and printing one
		// fixed sentence. Measured on tender_desk.py: FOUR gates raise
		// frappe.PermissionError — and therefore 403 — before the view check runs,
		// and only the last of them is about a view:
		//   :30 _assert_company_scope  "This request belongs to a company you cannot access."
		//   :31 _require_tender        "Not permitted" / "Tender module is not enabled for {0}."
		//   :36 no view role at all    "Access denied to Operations Desk."
		//   :51 _require_tender_view   "Not permitted"   (only reached `if view:`)
		// The :36 case is reachable with NO view in the URL. All four landed in one
		// branch reading "This view is not yours", and the server's sentence — the
		// only text that said what was actually wrong — was discarded. It arrives
		// already translated (client.js unwraps _server_messages), so it is printed,
		// not re-keyed.
		expect(regionText("forbidden", { forbiddenMessage: "Access denied to Operations Desk." })).toBe(
			"Access denied to Operations Desk."
		);
		expect(regionText("forbidden", { forbiddenMessage: "" })).toMatch(/roles/i);
	});

	it("offers the view recovery only when a view was actually requested", () => {
		// WHAT WOULD MAKE THIS FAIL: printing "Remove the view from the address"
		// under every refusal. Three of the four have no view in the address to
		// remove, so the one actionable sentence on the screen sends the reader
		// after a query parameter that is not there — and the reader who most needs
		// help (no view role at all, landing on a bare /tender/desk) is exactly the
		// one who gets it.
		const hint = (over) =>
			evalInScope(rhsOf("const forbiddenHint"), {
				computed: (fn) => fn(),
				t: (key) => key,
				forbidden: { value: true },
				forbiddenView: { value: "" },
				...over,
			});
		expect(hint({ forbiddenView: { value: "logist" } })).toMatch(/address/i);
		expect(hint({})).toBe("");
		expect(hint({ forbidden: { value: false }, forbiddenView: { value: "logist" } })).toBe("");
	});

	it("names the view the refused request asked for, not the one on screen now", () => {
		// WHAT WOULD MAKE THIS FAIL: reading currentView inside the catch. It is
		// reassigned by the response handler and by the picker, so the refusal would
		// describe a view the failed request never sent. Captured beside the request
		// token, which is the other thing that has to be pinned to one request.
		const body = src.slice(anchor("async function fetchDesk("), anchor("const regionState"));
		expect(body).toMatch(/const requestedView = currentView\.value \|\| "";[\s\S]*?\+\+reqToken;/);
		expect(body).toMatch(/forbiddenView\.value = requestedView;/);
		expect(body).toMatch(/forbiddenMessage\.value = err\?\.message \|\| "";/);
	});

	it("hides the counter strip while the view is refused", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving the four chips drawn. With no payload
		// they render 0 / 0 / 0 / 0 under their rules ("due date passed, still
		// open"), which reads as "nothing is overdue" — a measurement of a view the
		// server just declined to measure. Four confident zeros beside a refusal is
		// worse than either state alone.
		const at = anchor('class="ds-kpis" data-cols="4"');
		const tag = src.slice(src.lastIndexOf("<div", at), src.indexOf(">", at));
		expect(tag).toMatch(/v-if="regionState !== 'forbidden'"/);
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
			browserToday: { value: browser },
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

	it("reads the browser's calendar date into one place and nowhere else", () => {
		// WHAT WOULD MAKE THIS FAIL: a `todayIso()` call left behind at one of the
		// four sites todayStr drives (header, TODAY filter, calendar today cell, row
		// badge). Two sources of "today" in one screen is the defect this row exists
		// to close, and the second one would agree on every day a test is likely to
		// be run.
		//
		// This counted ONE call until 2026-09-02, which also forbade refreshing the
		// value — and review found the snapshot going stale on a desk left open
		// overnight. What matters is not how often it is called but that every call
		// lands in `browserToday` and every consumer reads it from there. Comments
		// are stripped first: two of them name `todayIso()` while explaining the UTC
		// bug and the staleness, and a test that counted those would count prose.
		const lines = scriptWithoutComments()
			.split("\n")
			.filter((line) => line.includes("todayIso()"));
		expect(lines.length, "todayIso() is no longer read at all").toBeGreaterThan(0);
		for (const line of lines) {
			expect(line, "todayIso() read outside browserToday").toMatch(
				/browserToday(\.value)? = .*todayIso\(\)/
			);
		}
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

describe("D14 — an empty plan says WHY it is empty", () => {
	// Both readings come off the SAME payload here, so the helper cannot drift
	// from the component: `approvalsState` is the computed the Decision box also
	// reads (D15), and the gap list must see exactly what the panel sees.
	const gaps = (payload) =>
		evalInScope(blockRhsOf("gaps"), {
			computed: (fn) => fn(),
			deskData: { value: payload },
			approvalsState: { value: payload?.approvals_state || "" },
			t: (key, params) =>
				params ? key.replace(/\{(\w+)\}/g, (_, k) => String(params[k])) : key,
		});

	/** The empty-plan branch: its `v-else-if` through the `<template v-else>` that draws rows. */
	const emptyBranch = () =>
		src.slice(anchor('v-else-if="filteredPlan.length === 0"'), rowsTemplate());

	it("names an approval queue that could not be read", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping the signal. Measured: the desk's
		// approval read was wrapped in a bare `except Exception` that produced an
		// empty list, so a failure and a quiet queue rendered identically — two
		// counters at 0, an empty Decision box, and a plan asserting the view was
		// up to date. Four confident statements out of one swallowed exception.
		expect(gaps({ approvals_state: "unreadable" })).toHaveLength(1);
		expect(gaps({ approvals_state: "unreadable" })[0]).toMatch(/approval/i);
	});

	it("counts the rows the engine could not date", () => {
		// WHAT WOULD MAKE THIS FAIL: ignoring `skipped`. build_plan has always
		// counted the rows it dropped for an unparseable date and the caller threw
		// the number away, so a lot with a malformed deadline disappeared and the
		// panel then said everything was up to date. The number must say how many.
		expect(gaps({ skipped: 2 })[0]).toMatch(/\b2\b/);
	});

	it("treats an approval queue that is not yours as an answer, not a gap", () => {
		// WHAT WOULD MAKE THIS FAIL: folding "you are not an approver" in with "the
		// query failed". Most of this desk's readers are not approvers; a plan that
		// omits approvals they could never act on is COMPLETE for them, and marking
		// it incomplete every single day would make the real gap invisible.
		expect(gaps({ approvals_state: "not_yours" })).toEqual([]);
		expect(gaps({ approvals_state: "read" })).toEqual([]);
		expect(gaps({})).toEqual([]);
	});

	it("reports both gaps when both happened", () => {
		// WHAT WOULD MAKE THIS FAIL: an if/else that reports the first gap only.
		// The reader needs to know everything that was not checked, not the first
		// thing that was not checked.
		expect(gaps({ approvals_state: "unreadable", skipped: 3 })).toHaveLength(2);
	});

	it("keeps 'up to date' behind BOTH the filter and the gap check", () => {
		// WHAT WOULD MAKE THIS FAIL: the sentence escaping into a general empty
		// state. "All items in this view are up to date" is a claim about the world.
		// It is only true when the plan is genuinely empty AND everything the desk
		// checks was checkable — never when a counter is merely hiding the rows, and
		// never when an input could not be read.
		const branch = emptyBranch();
		const claim = branch.indexOf('t("All items in this view are up to date.")');
		expect(claim).toBeGreaterThan(-1);
		expect(branch.slice(0, claim)).toMatch(/v-if="plan\.length"/);
		expect(branch.slice(0, claim)).toMatch(/v-else-if="gaps\.length"/);
		expect(branch.lastIndexOf("<template v-else>", claim)).toBeGreaterThan(
			branch.lastIndexOf('v-else-if="gaps.length"', claim)
		);
	});

	it("says the filter is what is hiding the rows, when it is", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving the filtered-empty case reading "No
		// tasks scheduled for today". Pressing Overdue on a day with three today
		// items would then report an empty desk — the single most reachable way to
		// make this screen lie, one click from the default view.
		const filtered = emptyBranch().slice(0, emptyBranch().indexOf('v-else-if="gaps.length"'));
		expect(filtered).toMatch(/\{ count: plan\.length \}/);
		expect(filtered).not.toMatch(/up to date/);
	});

	it("reads the plan from one place", () => {
		// WHAT WOULD MAKE THIS FAIL: `deskData.plan` inline in the branch beside
		// `filteredPlan`'s own copy. Two readings of one list is how the panel ends
		// up counting a different number from the one it filtered.
		expect(scriptWithoutComments().match(/deskData\.value\?\.plan/g)).toHaveLength(1);
	});
});

/**
 * One panel's source: the `<section` that opens it through the `</section>` that
 * closes it. Anchored on the panel's own heading, because all four panels carry
 * `ds-panel` and an index-based slice would silently follow a reorder.
 */
function panelBlock(heading) {
	const at = anchor(`<h3>{{ t("${heading}") }}</h3>`);
	return src.slice(src.lastIndexOf("<section", at), src.indexOf("</section>", at) + 10);
}

/** The `<section …>` open tag of a panel — where a whole-panel `v-if` would sit. */
function panelOpenTag(heading) {
	const block = panelBlock(heading);
	return block.slice(0, block.indexOf(">") + 1);
}

const SIDE_PANELS = ["Decision box", "Team load", "Next 7 days"];

/**
 * All four regions' sources, keyed by heading. The plan panel is included and its
 * heading is an `<h2>`: it is a region like the other three, and every test that
 * treats it as a special case is a test that cannot see the two chains diverge.
 */
function regionPanels() {
	const planAt = anchor('<h2>{{ t("Daily work plan") }}</h2>');
	const out = {
		"Daily work plan": src.slice(
			src.lastIndexOf("<section", planAt),
			src.indexOf("</section>", planAt) + 10
		),
	};
	for (const heading of SIDE_PANELS) out[heading] = panelBlock(heading);
	return out;
}

describe("D15 — every region renders the five states, not just the plan", () => {
	const regionScope = () => ({
		computed: (fn) => fn(),
		loading: { value: false },
		forbidden: { value: false },
		error: { value: "" },
		deskData: { value: {} },
		session: { canAccessModule: () => true, activeCompany: "Mikas" },
	});
	const regionState = (over = {}) =>
		evalInScope(blockRhsOf("regionState"), { ...regionScope(), ...over });

	it("resolves the gates in the plan panel's order when several are true at once", () => {
		// WHAT WOULD MAKE THIS FAIL: reordering the gates. Each pair below has an
		// opposite recovery: a refused view needs a ROLE, a failed request needs a
		// RETRY, an unset company needs a PICKER. Whichever gate answers first is
		// the sentence the reader acts on, so the order is the design — and while
		// the desk boots, several of them are true at the same time.
		const all = {
			loading: { value: true },
			forbidden: { value: true },
			error: { value: "boom" },
			session: { canAccessModule: () => false, activeCompany: "" },
		};
		const open = { canAccessModule: () => true, activeCompany: "Mikas" };
		expect(regionState(all)).toBe("loading");
		expect(regionState({ ...all, loading: { value: false } })).toBe("module");
		expect(
			regionState({
				...all,
				loading: { value: false },
				session: { canAccessModule: () => true, activeCompany: "" },
			})
		).toBe("company");
		expect(regionState({ ...all, loading: { value: false }, session: open })).toBe("forbidden");
		expect(
			regionState({
				...all,
				loading: { value: false },
				forbidden: { value: false },
				session: open,
			})
		).toBe("error");
		expect(regionState()).toBe("ready");
	});

	it("does not call a desk that has not answered yet empty", () => {
		// WHAT WOULD MAKE THIS FAIL: treating "no payload" as "ready". This is an
		// invariant, not a reproduction: the first render does precede onMounted,
		// but `loading` flips inside the same task and the reactive flush beats the
		// paint, so nobody has SEEN the empty frame. It is pinned because every
		// region's empty state is a claim about a payload — "nothing is due", "no
		// decision is waiting" — and a region that has not been given one has
		// measured nothing. Any future path that reaches these panels before the
		// first response (a cleared payload on view change, a second entry point)
		// inherits the answer instead of inventing one.
		expect(regionState({ deskData: { value: null } })).toBe("loading");
	});

	it("leaves every page-level gate to the one computed", () => {
		// WHAT WOULD MAKE THIS FAIL: any region deciding a gate for itself. This
		// replaces a test that could not fail: it compared each chain to a
		// hardcoded five-entry oracle and never to the other chain, so a sixth gate
		// added to one side was invisible from both — and the divergence was already
		// live. The plan panel had no `!deskData` state, so on the first paint three
		// panels said "loading" while the fourth said "I looked, there is nothing".
		// The oracle is now the source itself: a region may branch on its own
		// CONTENT, never on module, company, refusal, error or payload.
		const gate = /canAccessModule|activeCompany|\bforbidden\b|\berror\b|\bdeskData\b|\bloading\b/;
		for (const [heading, block] of Object.entries(regionPanels())) {
			const own = branchConditions(block).filter(
				(c) => gate.test(c) && !c.includes("regionState")
			);
			expect(own, `${heading} decides a page-level gate for itself`).toEqual([]);
		}
	});

	it("draws the shared states in all four regions, the plan panel included", () => {
		// WHAT WOULD MAKE THIS FAIL: a region opting out — which is how the two
		// chains came to exist in the first place. Counting call sites rather than
		// inspecting each panel is deliberate: a fifth region added tomorrow fails
		// this test until it reads the same computed.
		const panels = Object.entries(regionPanels());
		expect(panels).toHaveLength(4);
		for (const [heading, block] of panels) {
			const conditions = branchConditions(block);
			expect(conditions[0], `${heading} loading`).toBe("regionState === 'loading'");
			expect(conditions[1], `${heading} gates`).toBe("regionState !== 'ready'");
		}
	});

	it("gives every gate that is not the error its own sentence", () => {
		// WHAT WOULD MAKE THIS FAIL: a state added to the computed with no wording,
		// which renders as a blank panel foot — the same nothing the reader got
		// before any of this existed.
		const states = [...blockRhsOf("regionState").matchAll(/return "(\w+)"/g)].map((m) => m[1]);
		// Without this the loop passes by not running: a renamed computed or a
		// changed return style would report five green states and check none.
		expect(states.length, "no states extracted — the oracle went blind").toBeGreaterThan(4);
		const worded = liftConst("REGION_STATE_TEXT");
		for (const state of states) {
			if (["loading", "ready", "error"].includes(state)) continue;
			expect(worded, `no wording for state "${state}"`).toContain(`${state}:`);
		}
	});

	it("prints the server's own words in the error state", () => {
		// WHAT WOULD MAKE THIS FAIL: a generic "something went wrong" in place of
		// `error`. The message is the only diagnostic that crosses the wire; the
		// three gate states are known in advance and read from the map instead.
		expect(regionText("error", { error: "Row 4: bad date" })).toBe("Row 4: bad date");
		expect(regionText("module")).toMatch(/tender module/);
		expect(regionText("company")).toMatch(/company/i);
		expect(regionText("forbidden")).toMatch(/roles/i);
	});

	for (const heading of SIDE_PANELS) {
		it(`shows "${heading}" reading rather than nothing while the desk loads`, () => {
			// WHAT WOULD MAKE THIS FAIL: the panel rendering no skeleton. All four
			// regions come from ONE request, so the plan alone showing a skeleton
			// tells the reader the side column is finished when it has not started.
			expect(panelBlock(heading)).toMatch(
				/<SkeletonRows\s+v-if="regionState === 'loading'"/
			);
		});

		it(`never hides "${heading}" behind the length of its own data`, () => {
			// WHAT WOULD MAKE THIS FAIL: `v-if="teamLoad.length"` / `v-if="week.length"`
			// coming back. A section that removes itself is the one state a reader
			// cannot interrogate: the page is simply shorter, and a failed request,
			// a refused view and a genuinely quiet week are all rendered as absence.
			expect(panelOpenTag(heading)).not.toMatch(/v-if/);
		});

		it(`states the page-level gates inside "${heading}"`, () => {
			// WHAT WOULD MAKE THIS FAIL: leaving a region silent on module denial,
			// an unset company, a refused view or a failed load. Each of the three
			// panels is a claim about the world; none may be drawn, or blanked,
			// without saying which of those five things it is.
			expect(panelBlock(heading)).toMatch(/v-else-if="regionState !== 'ready'"/);
		});

		it(`announces only the failure in "${heading}", not the refusals`, () => {
			// WHAT WOULD MAKE THIS FAIL: a bare role="alert" on the shared branch.
			// It is an assertive live region — it interrupts a screen reader because
			// something BROKE. A module you do not have and a view you may not open
			// are policy outcomes, and three panels interrupting at once over one
			// policy outcome is three interruptions for no news.
			expect(panelBlock(heading)).toMatch(
				/:role="regionState === 'error' \? 'alert' : null"/
			);
		});
	}

	it("splits the Decision box's empty into the three things it can mean", () => {
		// WHAT WOULD MAKE THIS FAIL: one "No pending decisions" for all of them.
		// The box is fed by list_pending, which raises for a non-approver and can
		// fail outright; those two produce the same empty list as a genuinely quiet
		// queue. Only one of the three may claim nothing is pending — and it is the
		// only one of the three the reader can safely stop thinking about.
		const branch = panelBlock("Decision box");
		const claim = branch.indexOf('t("No pending decisions")');
		expect(claim).toBeGreaterThan(-1);
		expect(branch.slice(0, claim)).toMatch(/v-if="approvalsState === 'not_yours'"/);
		expect(branch.slice(0, claim)).toMatch(/v-else-if="approvalsState === 'unreadable'"/);
	});

	it("does not print a count over a box it just called unknown", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving `decisions.length` in the panel head.
		// The head would then read "0" directly above "unknown, not empty" — one
		// panel contradicting itself in two lines, and the numeral is the half a
		// reader believes. A queue that is not YOURS is different: nothing there
		// waits on you, so zero is the true answer and stays printed.
		const known = (state) =>
			evalInScope(rhsOf("const decisionsKnown"), {
				computed: (fn) => fn(),
				approvalsState: { value: state },
			});
		expect(known("unreadable")).toBe(false);
		expect(known("not_yours")).toBe(true);
		expect(known("read")).toBe(true);
		expect(panelBlock("Decision box")).toMatch(/decisionsKnown \? decisions\.length : "—"/);
	});

	it("reads the approval state from one place", () => {
		// WHAT WOULD MAKE THIS FAIL: `deskData.approvals_state` inline in the
		// template beside the computed the plan's gap list reads. The Decision box
		// and the empty plan describe the SAME swallowed exception; two readings is
		// how one of them ends up reporting it and the other not.
		expect(scriptWithoutComments().match(/deskData\.value\?\.approvals_state/g)).toHaveLength(1);
	});

	it("says the week is quiet instead of drawing seven dashes and no sentence", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping the calendar's empty state. Seven
		// cells reading "—" over a "PAST DUE —" foot is the panel's answer for "no
		// item is due" and for "this panel has nothing in it", and the two are the
		// same pixels. The dates stay drawn either way: the window is the panel.
		const branch = panelBlock("Next 7 days");
		expect(branch).toMatch(/v-if="calendarEmpty"/);
		expect(branch).toMatch(/ds-week/);
		const empty = evalInScope(blockRhsOf("calendarEmpty"), {
			computed: (fn) => fn(),
			pastDue: { value: { count: 0 } },
			week: { value: [{ count: 0 }, { count: 0 }] },
		});
		expect(empty).toBe(true);
	});

	it("does not call the week quiet while something is past due", () => {
		// WHAT WOULD MAKE THIS FAIL: computing emptiness from the seven cells only.
		// The past-due bucket is part of this panel (D13) and it is where the
		// desk's loudest rows live; a week with four overdue invoices behind it is
		// not a quiet week.
		const empty = (pastDue, week) =>
			evalInScope(blockRhsOf("calendarEmpty"), {
				computed: (fn) => fn(),
				pastDue: { value: { count: pastDue } },
				week: { value: week },
			});
		expect(empty(3, [{ count: 0 }])).toBe(false);
		expect(empty(0, [{ count: 0 }, { count: 2 }])).toBe(false);
	});
});

describe("D16 — the two empty Team loads are not the same empty", () => {
	it("distinguishes a panel that is not your role from a company with no lots", () => {
		// WHAT WOULD MAKE THIS FAIL: one empty state for both. `team_load` is built
		// only under `if oversight:` (tender_desk.py), so every non-director gets
		// [] — and so does a director of a company that has no lots at all. Today
		// both render as no panel. Merged, they tell a sourcing user that their
		// colleagues are idle, which is a claim the server never made.
		const branch = panelBlock("Team load");
		expect(branch).toMatch(/v-else-if="!oversight"/);
		expect(branch).toMatch(/v-else-if="!teamLoad\.length"/);
		expect(branch.indexOf('v-else-if="!oversight"')).toBeLessThan(
			branch.indexOf('v-else-if="!teamLoad.length"')
		);
	});

	it("takes the role answer from the server, never from an empty list", () => {
		// WHAT WOULD MAKE THIS FAIL: inferring "not your role" from `team_load`
		// being empty — which is the bug, restated as its own fix. Only the server
		// knows whether the reader holds an oversight role; the client can see
		// nothing but the consequence, and the consequence is ambiguous.
		expect(blockRhsOf("oversight")).toMatch(/deskData\.value\?\.oversight/);
		const value = (payload) =>
			evalInScope(blockRhsOf("oversight"), {
				computed: (fn) => fn(),
				deskData: { value: payload },
			});
		expect(value({ oversight: true, team_load: [] })).toBe(true);
		expect(value({ oversight: false, team_load: [] })).toBe(false);
		expect(value({ team_load: [] })).toBe(false);
		// An EMPTY list still proves nothing — that is this test's name. A populated
		// one is different evidence and is handled where the fallback is tested.
		expect(value({ oversight: false, team_load: [{ user: "a" }] })).toBe(false);
	});

	it("does not tell a director that nobody has work", () => {
		// WHAT WOULD MAKE THIS FAIL: wording the oversight empty as "no open lots".
		// The server inserts a row for EVERY deal owner and only then counts the
		// open ones, so a team whose lots are all won or lost still renders rows of
		// 0. An empty list therefore means the company has no lots at all — a
		// different sentence, and the only one this state is entitled to.
		const branch = panelBlock("Team load");
		const at = branch.indexOf('v-else-if="!teamLoad.length"');
		expect(at, "no empty-of-work branch to word").toBeGreaterThan(-1);
		const empty = branch.slice(at);
		expect(empty.slice(0, empty.indexOf("</div>"))).not.toMatch(/open lot/i);
	});
});

describe("review P2/P3 — the desk stops asserting things it has not measured", () => {
	it("prints — for the two approval counters it has just called unknown", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving `c.awaiting_me ?? 0` in the strip. When
		// the approval queue could not be read the empty plan says both approval
		// counters are unknown, not zero — and the two chips directly above it
		// printed a literal 0 under the rules "approval assigned to you" and "you
		// requested, someone else answers". The numeral is the half a reader
		// believes. The other two chips keep their numbers: due_today and overdue
		// come off the plan, not off the approval read.
		const strip = (payload, known) =>
			evalInScope(blockRhsOf("kpis"), {
				computed: (fn) => fn(),
				t: (key) => key,
				deskData: { value: payload },
				decisionsKnown: { value: known },
			});
		const counters = { due_today: 3, overdue: 2, awaiting_me: 0, waiting_others: 0 };
		const unknown = strip({ counters }, false);
		const byFilter = Object.fromEntries(unknown.map((k) => [k.filter, k.value]));
		expect(byFilter.awaiting_me).toBe("—");
		expect(byFilter.waiting_others).toBe("—");
		expect(byFilter.today).toBe(3);
		expect(byFilter.overdue).toBe(2);

		const known = Object.fromEntries(strip({ counters }, true).map((k) => [k.filter, k.value]));
		expect(known.awaiting_me).toBe(0);
		expect(known.waiting_others).toBe(0);
	});

	it("re-reads the device date on every load, not once at setup", () => {
		// WHAT WOULD MAKE THIS FAIL: `const browserToday = todayIso()` at setup. An
		// operations desk is the screen left open overnight. Past local midnight the
		// reader presses Refresh, the server's date advances and the snapshot does
		// not, so the meta row states "your device says <yesterday>" while the
		// device says today — D18's skew warning firing on the desk's own staleness
		// rather than on a real disagreement, every morning, until someone reloads.
		expect(rhsOf("const browserToday")).toMatch(/^ref\(todayIso\(\)\)$/);
		const body = src.slice(anchor("async function fetchDesk("), anchor("const regionState"));
		expect(body).toMatch(/browserToday\.value = todayIso\(\);/);
	});

	it("believes the server about oversight, and the data when the server is silent", () => {
		// WHAT WOULD MAKE THIS FAIL: `Boolean(deskData.value?.oversight)`, which
		// cannot tell "the server said false" from "the server did not say". Against
		// a server that has not shipped the flag yet — the deploy window this branch
		// creates — a director with a populated team_load read "This panel belongs
		// to the director view" printed over their own team's rows. Same treatment
		// D18 gives `today`: prefer the server, fall back to the only other
		// evidence, and never let the fallback overrule an explicit answer.
		const value = (payload) =>
			evalInScope(blockRhsOf("oversight"), {
				computed: (fn) => fn(),
				deskData: { value: payload },
			});
		expect(value({ oversight: true, team_load: [] })).toBe(true);
		expect(value({ oversight: false, team_load: [{ user: "a" }] })).toBe(false);
		expect(value({ team_load: [{ user: "a" }] })).toBe(true);
		expect(value({ team_load: [] })).toBe(false);
		expect(value(null)).toBe(false);
	});

	it("reports a gap on a desk that has rows, not only on an empty one", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving `gaps` reachable only through the
		// empty-plan branch, whose outer condition also requires plan.length === 0.
		// A desk with twelve rows and three more dropped for unparseable dates said
		// nothing at all — and a busy desk is exactly where a silently missing row
		// is least likely to be noticed and most likely to matter.
		const at = anchor('<h2>{{ t("Daily work plan") }}</h2>');
		const panel = src.slice(src.lastIndexOf("<section", at), src.indexOf("</section>", at));
		const rows = panel.slice(panel.indexOf("\n\t\t\t\t<template v-else>"));
		expect(rows).toMatch(/v-if="gaps\.length"/);
		expect(rows).toMatch(/v-for="gap in gaps"/);
	});
});
