import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/TenderFunnel.vue"), "utf8");

/**
 * F13 (docs/design/prompts/15-pipeline-overview.md, S3) — a failed funnel load
 * rendered nothing. The template had exactly two top-level branches,
 * `v-if="loading && !data"` and `v-else-if="data"`; the `finally` block always
 * clears `loading`, so once a request rejects, both conditions are false and
 * `<div class="tender-funnel">` is left with no children at all. That is worse
 * than a spinner stuck forever: there was no visual difference between "still
 * loading", "the pipeline is genuinely empty", and "the request failed".
 *
 * The only account of the failure was `toast.error(...)` — a few seconds of
 * text a reader who looked away never sees. Once it fades, the screen offers
 * no explanation and no way to tell a failed load from an empty pipeline.
 *
 * DOM-less per vitest.config.mjs. `load()` is lifted out of the source and run
 * for real against fake refs and a controllable `call`, because "the panel
 * ends up in a renderable state after a rejection" is a claim about behaviour
 * under a real async rejection, not something a source-text match can prove.
 */

function liftLoad(scope) {
	const fn = src.match(/^async function load\(\)[\s\S]*?^\}/m);
	expect(fn, "TenderFunnel.vue has no top-level load()").not.toBeNull();
	const keys = Object.keys(scope);
	return new Function(...keys, `${fn[0]}\nreturn load;`)(...keys.map((k) => scope[k]));
}

/** A scope of fake refs plus a `call` this test resolves or rejects by hand. */
function harness() {
	const activeCompany = { value: "Mikas" };
	const loading = { value: false };
	const data = { value: null };
	const error = { value: null };
	const props = { days: 90 };
	const emitted = [];
	let outcome = null;
	const scope = {
		activeCompany,
		loading,
		data,
		error,
		props,
		emit: (name, payload) => emitted.push([name, payload]),
		t: (s) => s,
		call: async () => {
			if (outcome.reject) throw outcome.reject;
			return outcome.resolve;
		},
	};
	return {
		...scope,
		emitted,
		setOutcome: (o) => (outcome = o),
		load: liftLoad(scope),
	};
}

describe("F13 — a failed load leaves the panel in a renderable state", () => {
	it("records the failure where the toast used to hide it", async () => {
		// WHAT WOULD MAKE THIS FAIL: going back to toast-only, i.e. never writing
		// to an `error` ref. The template would have nothing to key a new branch
		// off, and this fix could not exist without a second piece of bookkeeping.
		const h = harness();
		h.setOutcome({ reject: new Error("Tender module is not enabled for Mikas.") });
		await h.load();
		expect(h.error.value).toBe("Tender module is not enabled for Mikas.");
	});

	it("falls back to a translated message when the server sends none", async () => {
		// WHAT WOULD MAKE THIS FAIL: reading err.message without the `|| t(...)`
		// fallback -- a network-level rejection (no server response at all) has
		// no .message worth showing, and the panel would render an empty alert.
		const h = harness();
		h.setOutcome({ reject: new Error() });
		await h.load();
		expect(h.error.value).toBe("Could not load the tender funnel.");
	});

	it("leaves both the loading and the data conditions false -- this is S3 itself", async () => {
		// Not a claim about the fix: a reproduction of the defect. Both landing
		// false at once is exactly the state the OLD two-branch template had no
		// case for, which is why nothing rendered.
		const h = harness();
		h.setOutcome({ reject: new Error("nope") });
		await h.load();
		expect(h.loading.value).toBe(false);
		expect(h.data.value).toBeNull();
	});

	it("clears a previous failure once a retry succeeds", async () => {
		// WHAT WOULD MAKE THIS FAIL: setting `error` and never resetting it. The
		// new branch sits above `v-else-if="data"` in the same ladder as the
		// loading branch, so a stale error would keep a perfectly loaded funnel
		// off the screen for the rest of the session.
		const h = harness();
		h.setOutcome({ reject: new Error("nope") });
		await h.load();
		expect(h.error.value).toBe("nope");

		h.setOutcome({ resolve: { generated_at: "2026-09-02 10:00:00" } });
		await h.load();
		expect(h.error.value).toBeNull();
		expect(h.data.value).toEqual({ generated_at: "2026-09-02 10:00:00" });
	});
});

describe("F13 — the template renders the failure instead of nothing", () => {
	it("adds an error rung to the loading/data ladder", () => {
		// WHAT WOULD MAKE THIS FAIL: an `error` ref that nothing in the template
		// reads -- exactly the gap the behavioural tests above cannot see, since
		// they never touch the template.
		expect(src).toMatch(/v-else-if="error"/);
		const at = src.indexOf('v-else-if="error"');
		const branch = src.slice(at - 40, at + 200);
		expect(branch, "the error branch is not announced to assistive tech").toMatch(/role="alert"/);
		expect(branch, "the error branch does not print the message it recorded").toMatch(
			/\{\{\s*error\s*\}\}/
		);
	});

	it("no longer reports the load failure through a toast", () => {
		// WHAT WOULD MAKE THIS FAIL: keeping toast.error as a second, redundant
		// sink. This file had exactly one toast call site -- the one this fix
		// moved -- so its presence here would mean either the fix was only half
		// applied, or an orphaned `useToast` import survived the edit.
		expect(src).not.toMatch(/toast\.error\(/);
		expect(src).not.toMatch(/useToast/);
	});
});
