import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/DirectorBoard.vue"), "utf8");
const TEMPLATE = src.slice(src.indexOf("<template>"), src.indexOf("<style scoped>"));

/**
 * Acceptance row P13 (prompt 14, director board): a rejected assignment must
 * return the manager <select> to its previous value.
 *
 * Measured 2026-09-02 (prompt doc S5, tender.py assign_tender / :276-281 of
 * the doc): `<select :value="r.assigned_to" @change="assign(r,
 * $event.target.value)">`. assign() wrote row.assigned_to only on success; on
 * failure it raised a toast and returned. `:value` is a one-way bind — on
 * failure nothing reactive changes, so Vue never re-patches that binding, so
 * the <select> keeps showing whatever the BROWSER already set natively the
 * instant the user picked an option (Vue does not intercept that; it only
 * reconciles the DOM value when something it tracks changes). The toast
 * fades; the wrong name stays selected.
 *
 * The fix is necessarily imperative, not reactive: capture the row's value
 * before the request, and on rejection write it directly onto the DOM
 * element the change event already carries — there is no reactive value
 * whose mutation would make Vue re-sync a binding nothing else touched.
 *
 * DOM-less: assign() is new-Function-lifted (contractBoardReload.spec.js's
 * precedent), fed a plain `{ target: { value } }` stand-in for the change
 * event — the same shape a real DOM Event carries for what this function
 * actually reads and writes, without mounting anything.
 */

function deferred() {
	let resolve, reject;
	const promise = new Promise((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

function liftAssign(scope) {
	const fn = src.match(/^async function assign\(row, user, event\)[\s\S]*?^\}/m);
	expect(fn, "DirectorBoard.vue has no top-level assign(row, user, event)").not.toBeNull();
	const keys = Object.keys(scope);
	return new Function(...keys, `${fn[0]}\nreturn assign;`)(...keys.map((k) => scope[k]));
}

function harness() {
	const pending = [];
	const toasts = { success: [], error: [] };
	const scope = {
		t: (s) => s,
		toast: {
			success: (msg) => toasts.success.push(msg),
			error: (msg) => toasts.error.push(msg),
		},
		call: () => {
			const d = deferred();
			pending.push(d);
			return d.promise;
		},
	};
	return { ...scope, pending, toasts, assign: liftAssign(scope) };
}

describe("P13 — a rejected assignment visibly reverts", () => {
	it("reverts the DOM select's value to what it was before the rejected change", async () => {
		// WHAT WOULD MAKE THIS FAIL: today's assign(row, user) — no event
		// parameter to write back to, so the browser's own already-applied DOM
		// change survives a server refusal untouched.
		const h = harness();
		const row = { deal: "D1", assigned_to: "alice", assigned_to_name: "Alice" };
		const event = { target: { value: "bob" } };
		const run = h.assign(row, "bob", event);
		h.pending[0].reject(new Error("Not permitted"));
		await run;
		expect(event.target.value).toBe("alice");
		expect(row.assigned_to).toBe("alice");
		expect(h.toasts.error.length).toBe(1);
	});

	it("reverts to an empty (unassigned) previous value, not just a named one", async () => {
		// WHAT WOULD MAKE THIS FAIL: `event.target.value = previous || X` — an
		// empty string is a falsy but entirely valid "was unassigned" state, and
		// a fallback here would revert to the wrong thing for it specifically.
		const h = harness();
		const row = { deal: "D1", assigned_to: "", assigned_to_name: "" };
		const event = { target: { value: "carol" } };
		const run = h.assign(row, "carol", event);
		h.pending[0].reject(new Error("nope"));
		await run;
		expect(event.target.value).toBe("");
	});

	it("a confirmed assignment writes the row and leaves the DOM value alone", async () => {
		// WHAT WOULD MAKE THIS FAIL: reverting unconditionally regardless of
		// outcome, which would fight the user's own successful choice back to
		// the old manager on every assignment, not just a rejected one.
		const h = harness();
		const row = { deal: "D1", assigned_to: "alice", assigned_to_name: "Alice" };
		const event = { target: { value: "bob" } };
		const run = h.assign(row, "bob", event);
		h.pending[0].resolve({ assigned_to: "bob", assigned_to_name: "Bob" });
		await run;
		expect(row.assigned_to).toBe("bob");
		expect(row.assigned_to_name).toBe("Bob");
		expect(event.target.value).toBe("bob");
		expect(h.toasts.success.length).toBe(1);
	});

	it("captures the previous value from row.assigned_to before the request, not after", () => {
		// WHAT WOULD MAKE THIS FAIL: reading `row.assigned_to` inside the catch
		// instead of before the try — harmless here since nothing else in this
		// function mutates it first, but it is the source-level fact that makes
		// "previous" mean what the other three tests assume it means.
		const fn = src.match(/^async function assign\(row, user, event\)[\s\S]*?^\}/m)[0];
		const previousAt = fn.indexOf("const previous = row.assigned_to;");
		const tryAt = fn.indexOf("try {");
		expect(previousAt, "no `const previous = row.assigned_to;` found").toBeGreaterThan(-1);
		expect(tryAt, "no try block found").toBeGreaterThan(-1);
		expect(previousAt).toBeLessThan(tryAt);
	});

	it("the select passes its own change event through to assign()", () => {
		// WHAT WOULD MAKE THIS FAIL: the call site not forwarding $event, which
		// leaves assign() with nothing to write the revert onto even once it
		// knows to.
		expect(TEMPLATE).toMatch(/@change="assign\(r, \$event\.target\.value, \$event\)"/);
	});
});

describe("P13 follow-up (coordinator review, 2026-09-02) — two in-flight requests on the same select must not stomp each other", () => {
	it("a late rejection does not overwrite a value a different, already-successful call established", async () => {
		// WHAT WOULD MAKE THIS FAIL: today's unconditional `event.target.value =
		// previous` in the catch block. Two changes on the same <select> share
		// one DOM node, so both calls capture `previous` ("alice") before either
		// settles. The first pick (bob) succeeds — row.assigned_to moves to
		// "bob", and in a real mount Vue's one-way :value binding re-patches the
		// live DOM to "bob" the instant that reactive value changes. A LATE
		// rejection of the second pick (carol) must not blindly write "alice"
		// back over that: it would show a manager who is not actually assigned
		// server-side, which is strictly worse than the pre-P13 bug (that at
		// least left the user's own last choice on screen). The fix only
		// permits the revert while the select still shows exactly what THIS
		// call itself set — i.e. nothing else has touched it since.
		const h = harness();
		const row = { deal: "D1", assigned_to: "alice", assigned_to_name: "Alice" };
		const target = { value: "bob" }; // browser already applied the first pick natively
		const runA = h.assign(row, "bob", { target });

		target.value = "carol"; // browser applies the user's second pick before A settles
		const runB = h.assign(row, "carol", { target });

		h.pending[0].resolve({ assigned_to: "bob", assigned_to_name: "Bob" });
		await runA;
		expect(row.assigned_to).toBe("bob");
		// Vue's :value binding re-patches the live DOM the instant row.assigned_to
		// changes reactively — that is what a real mount does here. The lifted
		// function has no Vue attached, so the patch is applied by hand.
		target.value = "bob";

		h.pending[1].reject(new Error("Not permitted"));
		await runB;

		expect(target.value, "a late rejection must not stomp a newer, successful assignment").toBe("bob");
		expect(row.assigned_to).toBe("bob");
		expect(h.toasts.error.length).toBe(1);
	});
});
