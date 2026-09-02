import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/sales/SalesOrderBoard.vue"), "utf8");

/**
 * The contract board's five states (prompt 18, acceptance row C7).
 *
 * As measured 2026-09-02 the board had two branches: a spinner, then
 * `v-else-if="!stages.length"` rendering "No stages yet. / Add a stage to start
 * tracking contracts." That one branch answered for five different situations —
 * the request failed, the user has no tender role, the company has the module
 * off, no company is selected yet, and the board genuinely has no stages.
 *
 * Every other screen in the package fails into a sentence that is merely wrong.
 * This one failed into a CALL TO ACTION for a write the reader is usually not
 * entitled to perform — and taking it produced a refusal on the same toast
 * channel that had already swallowed the original error.
 *
 * The ladder here is OperationsDesk.vue's, which has had it since prompt 13's
 * measurement: module gate, company gate, error, then empty. The client gate is
 * a faithful mirror of the server's — `_require_tender` (api/tender.py:41) fails
 * on the role OR the company's enable_tender flag, and session.canAccessModule
 * ANDs exactly those two (stores/session.js:52-64).
 *
 * The behavioural half — that load() records the failure rather than only
 * toasting it — lives in contractBoardReload.spec.js, where load() is already
 * lifted and driven against a controllable `call`.
 */

/** Conditions of the top-level render ladder, in source order. */
function ladder() {
	const from = src.indexOf('v-if="loading"');
	expect(from, "the loading branch is gone").toBeGreaterThan(-1);
	const to = src.indexOf('v-else class="d-flex gap-3');
	expect(to, "the columns branch is gone — has the ladder's last rung moved?").toBeGreaterThan(from);
	const region = src.slice(from, to);
	return [...region.matchAll(/v-(?:else-)?if="([^"]*)"/g)].map((m) => m[1]);
}

/** Source of the branch whose condition is `cond`, back to its opening tag. */
function branch(cond) {
	const at = src.indexOf(`v-else-if="${cond}"`);
	expect(at, `no branch for ${cond}`).toBeGreaterThan(-1);
	const open = src.lastIndexOf("<", at);
	return src.slice(open, src.indexOf(">", at) + 1);
}

describe("C7 — five states, and the empty one stops answering for four others", () => {
	it("asks the questions in the order that makes each answer true", () => {
		// WHAT WOULD MAKE THIS FAIL: the two-branch ladder coming back, or a new
		// state being appended AFTER !stages.length. Order is the whole mechanism
		// here: these are v-else-if rungs, so the first true one wins and anything
		// below an always-reachable condition is dead markup. `!stages.length` is
		// true in all five situations, which is exactly why it must be asked last.
		expect(ladder()).toEqual([
			"loading",
			"!session.canAccessModule('tender')",
			"!activeCompany",
			"error",
			"!stages.length",
		]);
	});

	it("offers the write on exactly one rung", () => {
		// WHAT WOULD MAKE THIS FAIL: copying the "Add a stage" subtitle onto the
		// refusal or the error. That is the original defect in a new place — the
		// board telling a reader to create something in answer to a question they
		// did not ask and a permission they may not have.
		const invitations = src.match(/Add a stage to start tracking contracts\./g) ?? [];
		expect(invitations).toHaveLength(1);
		expect(branch("!stages.length")).toMatch(/ti-layout-kanban/);
	});

	it("announces the failure to assistive tech", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping role="alert". The error replaces the
		// board in place with no focus change and no sound; without the role a
		// screen-reader user is told nothing at all happened, which is
		// indistinguishable from the empty board it replaced.
		expect(branch("error")).toMatch(/role="alert"/);
	});

	it("distinguishes the refusal from the failure by tone as well as words", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving every state on the default primary
		// tone. Four EmptyStates that differ only in a sentence read as one screen
		// with changing text; the reader has to finish reading to learn whether
		// anything is wrong. A refusal is not an error and neither is an empty
		// board — see EmptyState.vue's `tone` prop.
		expect(branch("!session.canAccessModule('tender')")).toMatch(/tone="warning"/);
		expect(branch("!activeCompany")).toMatch(/tone="warning"/);
		expect(branch("error")).toMatch(/tone="danger"/);
		expect(branch("!stages.length")).not.toMatch(/tone="danger"/);
	});

	it("hides Add stage when the write is already known to be refused", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving the header action unconditional. The
		// empty state would stop inviting the write while the button beside the
		// title kept offering it — the same defect, moved four inches up. The
		// button stays on `error`: a load can fail transiently and still leave the
		// reader entitled to add a stage.
		const at = src.search(/<template[^>]*#actions>/);
		expect(at, "the board has no #actions slot").toBeGreaterThan(-1);
		const actions = src.slice(at, src.indexOf("</template>", at));
		expect(actions).toMatch(/v-if="session\.canAccessModule\('tender'\) && activeCompany"/);
	});

	it("keeps every state reachable — no branch shadows another", () => {
		// WHAT WOULD MAKE THIS FAIL: two rungs with the same condition, or a
		// condition repeated further down where it can never be true. Cheap to
		// assert, and it is the failure mode a hand-ordered v-else-if chain has.
		const conds = ladder();
		expect(new Set(conds).size).toBe(conds.length);
	});
});

/** Source between `from` and `to` markers. */
function region(from, to) {
	const a = src.indexOf(from);
	const b = src.indexOf(to, a + 1);
	expect(a, `marker ${from} not found`).toBeGreaterThan(-1);
	expect(b, `marker ${to} not found after ${from}`).toBeGreaterThan(a);
	return src.slice(a, b);
}

const loadingBranch = () => region('v-if="loading"', "<EmptyState");
const columnsBranch = () => region('v-else class="d-flex gap-3', "</template>");

describe("C9 — loading looks like the board that is coming", () => {
	it("renders no spinner anywhere in the file", () => {
		// WHAT WOULD MAKE THIS FAIL: the spinner coming back. It was the only
		// `spinner-border` among the module's boards — the other eight render
		// SkeletonRows — and it said "something is happening" where the reader
		// needed "columns are coming".
		// (boolean form: a failing toMatch would print the whole component.)
		expect(/spinner-border/.test(src), "spinner-border is back").toBe(false);
	});

	it("uses the placeholder utilities the rest of the SPA already uses", () => {
		// WHAT WOULD MAKE THIS FAIL: inventing a skeleton for this one screen.
		// SkeletonRows is rooted in a <tbody> (SkeletonRows.vue:10) and cannot
		// stand outside a table, and `ds-skel-stack` — drafted for exactly this
		// case in docs/design/2026-09-01-asama-a-delta.css — is not in the layer
		// yet (measured 2026-09-02: zero occurrences in stabler-modernist.css).
		// Bootstrap's placeholder/placeholder-glow is what the other fifteen
		// non-table loading sites in this SPA use, and it needs no new CSS.
		const branch = loadingBranch();
		expect(branch).toMatch(/placeholder-glow/);
		expect((branch.match(/class="placeholder col-/g) ?? []).length).toBeGreaterThanOrEqual(3);
	});

	it("holds the real board's column width, so nothing jumps when data lands", () => {
		// WHAT WOULD MAKE THIS FAIL: the two widths drifting apart. A skeleton
		// whose columns are a different width than the board's is a layout shift
		// dressed as a loading state — the reader watches the thing they were
		// about to click move. Asserting the RELATIONSHIP rather than the number
		// means changing the board's column width fails here until the skeleton
		// follows it.
		const width = (r) => r.match(/width: (\d+px)/)?.[1];
		expect(width(loadingBranch())).toBe(width(columnsBranch()));
		expect(width(columnsBranch())).toBeTruthy();
	});

	it("stands in the same space the board will occupy", () => {
		// WHAT WOULD MAKE THIS FAIL: a skeleton that does not reserve the board's
		// height. The page would grow when the columns arrive, which on a screen
		// whose whole job is horizontal scrolling moves the scroll position too.
		expect(loadingBranch()).toMatch(/min-height: 65vh/);
		expect(columnsBranch()).toMatch(/min-height: 65vh/);
	});

	it("does not offer a drop target that answers to nothing", () => {
		// WHAT WOULD MAKE THIS FAIL: copying the real column's dragover/drop
		// handlers into the skeleton along with its shape. A placeholder column
		// that accepts a card would call onDrop with a stage name that does not
		// exist — and there is nothing to drag yet anyway.
		const branch = loadingBranch();
		expect(branch).not.toMatch(/@drop/);
		expect(branch).not.toMatch(/draggable/);
	});
});
