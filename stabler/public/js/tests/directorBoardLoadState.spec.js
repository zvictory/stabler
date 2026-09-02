import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/DirectorBoard.vue"), "utf8");
const TEMPLATE = src.slice(src.indexOf("<template>"), src.indexOf("<style scoped>"));

/**
 * Acceptance rows P10 and P16 (prompt 14, director board) — both live in
 * load()'s failure handling (S3), so they share one harness.
 *
 * P10: load() had no error state at all — every failure (a 500, a dropped
 * connection, a permission refusal) fell into the same toast-then-silence
 * path, and the table's only account of "nothing came back" was the ordinary
 * empty-filters footer: "No tenders match these filters." A director cannot
 * tell a genuinely empty portfolio from a server that never answered.
 *
 * P16: useAutoRefresh(load) means load() runs unattended on a screen a
 * director leaves open (:70/:253 in the prompt doc). Because `data.value` is
 * left untouched on failure — arguably right, per S3 — a failed background
 * refresh keeps the LAST GOOD numbers on screen with nothing saying they are
 * no longer current. The fix keeps that choice (no data loss, the simpler of
 * the two the doc offers) and adds the missing half: a marker, so "stale" and
 * "fresh" are not the same pixels.
 *
 * DOM-less, `new Function`-lifted like contractBoardReload.spec.js. `error`
 * and `everLoaded` are plain `{value}` stand-ins load() is given, matching
 * that file's own harness shape (no real Vue ref, since only .value is ever
 * read). `stale` is a one-line computed the source defines directly from
 * those two — lifted by capturing its own arrow-function body, not
 * reimplemented, so a change to the real condition fails this test instead
 * of a copy of it.
 */

function deferred() {
	let resolve, reject;
	const promise = new Promise((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

/* load() gates on `await session.ensureTenderViews()` before it ever calls
 * call() (P11's zero-requests-when-refused contract), so call()'s push into
 * `pending` lands a microtask after load() is invoked, not synchronously
 * inside it. Draining a handful of already-resolved promises flushes that
 * queue without pinning an exact tick count to engine internals. */
async function flush() {
	for (let i = 0; i < 4; i++) await Promise.resolve();
}

function liftLoad(scope) {
	const fn = src.match(/^async function load\(\)[\s\S]*?^\}/m);
	expect(fn, "DirectorBoard.vue has no top-level load()").not.toBeNull();
	const keys = Object.keys(scope);
	return new Function(...keys, `${fn[0]}\nreturn load;`)(...keys.map((k) => scope[k]));
}

function liftStale() {
	const m = src.match(/^const stale = computed\(\(\) => (.+)\);$/m);
	expect(m, "DirectorBoard.vue defines no top-level `const stale = computed(() => ...)`").not.toBeNull();
	return new Function("error", "everLoaded", `return ${m[1]};`);
}

function harness() {
	const activeCompany = { value: "A" };
	const data = { value: { rows: [], kpi: {}, currency: "" } };
	const loading = { value: false };
	const error = { value: "" };
	const everLoaded = { value: false };
	const pending = [];
	const scope = {
		activeCompany,
		data,
		loading,
		error,
		everLoaded,
		canDirector: { value: true },
		session: { ensureTenderViews: () => Promise.resolve(["director"]) },
		t: (s) => s,
		call: () => {
			const d = deferred();
			pending.push(d);
			return d.promise;
		},
	};
	return { ...scope, pending, load: liftLoad(scope) };
}

const payload = (tag) => ({ rows: [{ deal: tag }], kpi: { count: 1 }, generated_at: "2026-09-02 09:00:00" });

describe("P10 — a failed load is an error, not a quiet empty board", () => {
	it("leaves everLoaded false and records the message on the very first failure", async () => {
		// WHAT WOULD MAKE THIS FAIL: swallowing the error into a toast again,
		// which is today's state — nothing on `error`, nothing distinguishing
		// this from a portfolio that is genuinely empty.
		const h = harness();
		const run = h.load();
		await flush();
		h.pending[0].reject(new Error("Tender module is not enabled for A."));
		await run;
		expect(h.error.value).toBe("Tender module is not enabled for A.");
		expect(h.everLoaded.value).toBe(false);
	});

	it("clears a previous error once a load succeeds", async () => {
		// WHAT WOULD MAKE THIS FAIL: never resetting `error`, which would leave
		// an error message on screen forever after the very next successful
		// refresh quietly fixed itself.
		const h = harness();
		const first = h.load();
		await flush();
		h.pending[0].reject(new Error("nope"));
		await first;
		expect(h.error.value).toBe("nope");

		const second = h.load();
		await flush();
		h.pending[1].resolve(payload("A"));
		await second;
		expect(h.error.value).toBe("");
		expect(h.everLoaded.value).toBe(true);
	});

	it("the table's empty-footer message is not shown while a hard error stands", () => {
		// WHAT WOULD MAKE THIS FAIL: the old unconditional ladder —
		// `v-if="!loading && !filteredRows.length"` as the FIRST branch —
		// coming back. A reader would be told to clear filters for a portfolio
		// the server never sent.
		const footAt = TEMPLATE.indexOf('class="board-scroll"');
		const footEnd = TEMPLATE.indexOf("</section>", footAt);
		expect(footAt, "board-scroll not found").toBeGreaterThan(-1);
		expect(footEnd, "no </section> after board-scroll").toBeGreaterThan(footAt);
		const foot = TEMPLATE.slice(footAt, footEnd);
		const errorAt = foot.indexOf("error && !everLoaded");
		const emptyAt = foot.indexOf("No tenders match these filters");
		expect(errorAt, "no branch keyed on error && !everLoaded").toBeGreaterThan(-1);
		expect(emptyAt, "the empty-filters message was removed rather than reordered").toBeGreaterThan(-1);
		expect(errorAt, "the error branch must be checked before the empty-filters branch").toBeLessThan(
			emptyAt
		);
	});

	it("prints the error itself, not new invented copy", () => {
		// WHAT WOULD MAKE THIS FAIL: this screen is on
		// test_tender_dashboard_i18n.py's strict allowlist — every literal t()
		// key introduced here needs a matching row in all five catalogues, and
		// this repo's workflow is "new keys are allowed, the catalogues are not
		// mine to edit". The error branch stays translation-neutral BECAUSE it
		// prints `error` (already-translated server text, or the pre-existing
		// fallback t("Could not load the director board.")) and adds no new
		// literal string of its own.
		const footAt = TEMPLATE.indexOf('class="board-scroll"');
		const footEnd = TEMPLATE.indexOf("</section>", footAt);
		const foot = TEMPLATE.slice(footAt, footEnd);
		const branchAt = foot.indexOf("error && !everLoaded");
		const branchEnd = foot.indexOf("</div>", branchAt);
		const branch = foot.slice(branchAt, branchEnd);
		expect(branch).toMatch(/\{\{\s*error\s*\}\}/);
		expect(branch.match(/t\(/g)?.length ?? 0).toBe(0);
	});
});

describe("P10 follow-up (coordinator review, 2026-09-02) — the ensureTenderViews round-trip is not a hole in P10", () => {
	it("loading is true for the whole ensureTenderViews round-trip, and a rejection there is not silent", async () => {
		// WHAT WOULD MAKE THIS FAIL: `await session.ensureTenderViews()` sitting
		// OUTSIDE the try, with `loading.value = true` moved to after it — this
		// file's own regression from the P10/P16 commit, caught on review.
		// `ensureTenderViews()` returns the raw call(...) chain (session.js) and
		// rejects when stabler.api.tender.tender_views fails; load() would then
		// throw before error/everLoaded/loading are ever touched, landing on the
		// exact "No tenders match these filters." defect P10 exists to close —
		// reachable on every cold load, not just a background refresh. And for
		// the whole round-trip beforehand, loading read false with zero rows,
		// which .claude/rules/10-frontend.md calls worse than the spinner it
		// bans: a false empty state, not even a spinner in a void.
		let ensureReject;
		const ensureTenderViews = () => new Promise((_resolve, reject) => { ensureReject = reject; });
		const scope = {
			activeCompany: { value: "A" },
			data: { value: { rows: [], kpi: {}, currency: "" } },
			loading: { value: false },
			error: { value: "" },
			everLoaded: { value: false },
			canDirector: { value: true },
			session: { ensureTenderViews },
			t: (s) => s,
			call: () => {
				throw new Error("call() must not run before ensureTenderViews settles");
			},
		};
		const load = liftLoad(scope);
		const run = load();
		expect(scope.loading.value, "loading must already be true, synchronously, before the first await").toBe(
			true
		);
		ensureReject(new Error("Tender module is not enabled for A."));
		await run;
		expect(scope.error.value).toBe("Tender module is not enabled for A.");
		expect(scope.everLoaded.value).toBe(false);
		expect(scope.loading.value).toBe(false);
	});
});

describe("P16 — a stale board after a failed auto-refresh says it is stale", () => {
	it("is false on the very first, never-succeeded load", () => {
		// WHAT WOULD MAKE THIS FAIL: computing staleness from `error` alone.
		// "Never loaded" and "loaded once, then a refresh failed" would render
		// as the same board unless everLoaded is part of the condition — this is
		// P10's hard-error case, and it must not also claim "stale".
		const stale = liftStale();
		expect(stale({ value: "boom" }, { value: false })).toBe(false);
	});

	it("is true only once a good load has happened and the next one fails", () => {
		// WHAT WOULD MAKE THIS FAIL: never flipping it at all, which is today's
		// behaviour — data.value keeps the last good payload with nothing next
		// to it saying a refresh already came back and failed.
		const stale = liftStale();
		expect(stale({ value: "" }, { value: true })).toBe(false);
		expect(stale({ value: "boom" }, { value: true })).toBe(true);
	});

	it("load() leaves data untouched on a failed refresh — the design constraint stale exists to cover", async () => {
		// WHAT WOULD MAKE THIS FAIL: load() clearing `data` on catch. The prompt
		// doc calls last-known-numbers-plus-a-marker a deliberate choice, not an
		// accident; this pins the half of it load() is responsible for.
		const h = harness();
		const first = h.load();
		await flush();
		h.pending[0].resolve(payload("A"));
		await first;
		const loaded = h.data.value;

		const second = h.load();
		await flush();
		h.pending[1].reject(new Error("timeout"));
		await second;
		expect(h.data.value).toBe(loaded);
		expect(h.error.value).toBe("timeout");
		expect(h.everLoaded.value).toBe(true);
	});

	it("the meta strip renders the marker only when stale, beside the freshness stamp", () => {
		// WHAT WOULD MAKE THIS FAIL: no v-if guard — the chip would then read
		// "refresh failed" on a board that loaded cleanly, which is worse than
		// not having the feature.
		const metaAt = TEMPLATE.indexOf("#meta");
		const metaEnd = TEMPLATE.indexOf("</template>", metaAt);
		const meta = TEMPLATE.slice(metaAt, metaEnd);
		expect(meta).toMatch(/v-if="stale"/);
	});
});
