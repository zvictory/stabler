import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/sales/SalesOrderBoard.vue"), "utf8");

/**
 * The contract board follows the active company (prompt 18, acceptance row C12).
 *
 * Measured 2026-09-02: this was the only screen in the tender module with no
 * `watch(activeCompany, …)`. Its imports were `{ computed, onMounted, ref }` —
 * `watch` was not even pulled in. Switching company left the previous company's
 * contracts on screen until the reader navigated away and back, and a session
 * that resolved its company AFTER mount never loaded at all: `load()` returns
 * early on a falsy company, so the board sat on "No stages yet. Add a stage to
 * start tracking contracts." — an invitation to write, caused by a race.
 *
 * The four read-only sibling screens use a bare `watch(activeCompany, load)`.
 * This one also carries a request token, which they do not, because it is the
 * only board in the module that WRITES: it moves cards between stages, adds and
 * deletes stages, and mutates `cards` in place while a drag is optimistic. A
 * late answer from the previous company does not just look stale here — it
 * repopulates the board underneath a reader who is dragging.
 *
 * DOM-less per vitest.config.mjs. `load` is lifted out of the source and run for
 * real against fake refs and a controllable `call`, because "the later request
 * wins" is a claim about behaviour under interleaving that no source-text match
 * can make.
 */

/** A promise whose resolution this test controls. */
function deferred() {
	let resolve, reject;
	const promise = new Promise((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

/**
 * Lift `let reqToken …` and `async function load()` out of the component and
 * return a callable bound to the supplied scope. The token declaration is
 * lifted rather than re-declared here so that deleting it from the component
 * breaks this test instead of leaving it passing against a private copy.
 */
function liftLoad(scope) {
	const decl = src.match(/^let reqToken = 0;$/m);
	expect(decl, "SalesOrderBoard.vue declares no reqToken").not.toBeNull();
	const fn = src.match(/^async function load\(\)[\s\S]*?^\}/m);
	expect(fn, "SalesOrderBoard.vue has no top-level load()").not.toBeNull();
	const keys = Object.keys(scope);
	return new Function(...keys, `${decl[0]}\n${fn[0]}\nreturn load;`)(...keys.map((k) => scope[k]));
}

/** A scope of fake refs plus a `call` this test resolves by hand. */
function harness() {
	const activeCompany = { value: "" };
	const board = { value: null };
	const cards = { value: [] };
	const loading = { value: false };
	const errors = [];
	const inflight = {};
	const error = { value: "" };
	const scope = {
		activeCompany,
		board,
		cards,
		loading,
		error,
		route: { query: {} },
		toast: { error: (m) => errors.push(m) },
		t: (s) => s,
		call: (_method, args) => (inflight[args.company] = deferred()).promise,
	};
	return { ...scope, errors, inflight, load: liftLoad(scope) };
}

const payload = (tag) => ({ stages: [{ name: tag }], cards: [{ name: tag }], generated_at: `2026-09-02 0${tag.length}:00:00` });

describe("C12 — the board follows the active company", () => {
	it("re-fetches when the company changes", () => {
		// WHAT WOULD MAKE THIS FAIL: removing the watch. Every other screen in the
		// module has one; this board had none, so it kept rendering the previous
		// company's contracts — with that company's money totals under the new
		// company's header — until the reader happened to navigate away.
		// (boolean form: a failing toMatch here would print the whole component.)
		expect(/watch\(activeCompany, load\)/.test(src), "no watch on activeCompany").toBe(true);
		expect(/import \{[^}]*\bwatch\b[^}]*\} from "vue"/.test(src), "watch is not imported").toBe(true);
	});

	it("loads once the session finally resolves a company", async () => {
		// WHAT WOULD MAKE THIS FAIL: relying on onMounted alone. load() returns
		// early while activeCompany is falsy, and mount can happen first — the
		// board then sits forever on the empty state, which on this screen reads
		// "Add a stage to start tracking contracts." A read failing into a write
		// invitation is the defect; this is the race that reaches it.
		const h = harness();
		await h.load(); // mounted before the session answered
		expect(h.board.value).toBeNull();

		h.activeCompany.value = "Mikas";
		const pending = h.load(); // what the watch fires
		h.inflight.Mikas.resolve(payload("Mikas"));
		await pending;
		expect(h.board.value?.stages).toEqual([{ name: "Mikas" }]);
	});

	it("keeps the later company's board when the earlier answer arrives last", async () => {
		// WHAT WOULD MAKE THIS FAIL: dropping the token, which is what a bare
		// `watch(activeCompany, load)` — the sibling screens' shape — would leave.
		// Switching A→B puts two requests in flight; if A answers second it
		// overwrites board and cards with A's contracts while the header, the
		// company selector and every subsequent write say B. This board writes:
		// the next drag would move a card the reader is not looking at.
		const h = harness();
		h.activeCompany.value = "A";
		const first = h.load();
		h.activeCompany.value = "B";
		const second = h.load();

		h.inflight.B.resolve(payload("B"));
		await second;
		h.inflight.A.resolve(payload("AA"));
		await first;

		expect(h.cards.value).toEqual([{ name: "B" }]);
		expect(h.board.value?.stages).toEqual([{ name: "B" }]);
	});

	it("does not lift the loading flag when a superseded request finishes", async () => {
		// WHAT WOULD MAKE THIS FAIL: guarding the assignment but not the finally
		// block. The stale response would then clear `loading` while the current
		// request is still in flight, so the spinner disappears and the board
		// renders its empty state — "No stages yet" — over a board that is simply
		// still loading. Same wrong screen, reached by the other half of the race.
		const h = harness();
		h.activeCompany.value = "A";
		const first = h.load();
		h.activeCompany.value = "B";
		const second = h.load();

		h.inflight.A.resolve(payload("AA"));
		await first;
		expect(h.loading.value, "a superseded response cleared the spinner").toBe(true);

		h.inflight.B.resolve(payload("B"));
		await second;
		expect(h.loading.value).toBe(false);
	});

	it("still reports a failure of the request that is current", async () => {
		// WHAT WOULD MAKE THIS FAIL: swallowing every error while guarding the
		// stale ones. The board would fail into its empty state in silence, which
		// is the C7 defect this change must not make worse.
		//
		// The failure is recorded on `error`, not on the toast: C7 moved it there
		// so the account of what happened stays where the board would have been.
		// This spec's own toast collector is asserted empty for that reason.
		const h = harness();
		h.activeCompany.value = "A";
		const only = h.load();
		h.inflight.A.reject(new Error("nope"));
		await only;
		expect(h.error.value).toBe("nope");
		expect(h.errors).toEqual([]);
		expect(h.loading.value).toBe(false);
	});
});

/**
 * C7's behavioural half. It lives here rather than in contractBoardStates.spec.js
 * because it is a claim about what load() DOES, and the harness that drives load()
 * against a controllable `call` is above. The ladder those states render through
 * is asserted there.
 */
describe("C7 — load() records the failure it used to only toast", () => {
	it("puts the server's message where the board would have been", async () => {
		// WHAT WOULD MAKE THIS FAIL: going back to toast-only. The board would fall
		// through to !stages.length and tell the reader to add a stage, while the
		// only account of what actually happened expired in a corner of the screen.
		const h = harness();
		h.activeCompany.value = "A";
		const only = h.load();
		h.inflight.A.reject(new Error("Tender module is not enabled for A."));
		await only;
		expect(h.error.value).toBe("Tender module is not enabled for A.");
	});

	it("clears a previous failure before the next attempt can be judged", async () => {
		// WHAT WOULD MAKE THIS FAIL: setting error and never resetting it. The
		// error rung sits ABOVE the board in the ladder, so a stale message would
		// keep a perfectly loaded board off the screen for the rest of the session.
		const h = harness();
		h.activeCompany.value = "A";
		const failed = h.load();
		h.inflight.A.reject(new Error("nope"));
		await failed;
		expect(h.error.value).toBe("nope");

		h.activeCompany.value = "B";
		const ok = h.load();
		h.inflight.B.resolve(payload("B"));
		await ok;
		expect(h.error.value).toBe("");
	});

	it("does not show an error belonging to a company the reader has left", async () => {
		// WHAT WOULD MAKE THIS FAIL: an unguarded catch — the same race C12's token
		// closes, reached through the error path. A superseded failure would blank a
		// board that had loaded correctly and blame it on the wrong company.
		//
		// This replaces C12's "does not toast an error from a request nobody is
		// waiting for", which asserted an empty toast list — vacuous once C7 moved
		// failures off the toast, because nothing fills that list any more.
		const h = harness();
		h.activeCompany.value = "A";
		const first = h.load();
		h.activeCompany.value = "B";
		const second = h.load();

		h.inflight.A.reject(new Error("A timed out"));
		await first;
		h.inflight.B.resolve(payload("B"));
		await second;

		expect(h.error.value).toBe("");
		expect(h.cards.value).toEqual([{ name: "B" }]);
	});
});
