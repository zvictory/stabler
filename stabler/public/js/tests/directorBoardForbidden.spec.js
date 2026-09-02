import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/DirectorBoard.vue"), "utf8");
const TEMPLATE = src.slice(src.indexOf("<template>"), src.indexOf("<style scoped>"));

/**
 * Acceptance row P11 (prompt 14, director board): a user without the
 * director view must see a refusal, not an empty board.
 *
 * Measured 2026-09-02 (prompt doc §2): tender_director_board's only gate is
 * `_require_tender_view("director", company)` (tender.py:2193) — there is no
 * sourcing/declarant/logist variant of this screen. Before this row, load()
 * had no gate at all on the client: a non-director's request would round-trip
 * to the server, get refused, and fall into the same toast-then-silence path
 * P10 already found — six counters at zero, an empty table, "No tenders match
 * these filters." The doc is explicit that this is not a new design problem:
 * "The finished answer is already in the repository" — TenderOverview.vue's
 * `ov-empty` panel, titled "Your work is on the operations desk" with a link
 * to the desk — "cite prompt 15 §2 rather than designing this twice."
 *
 * TenderFunnel is inside the same gate for a reason specific to this screen:
 * tender_funnel's own permission check is `_require_any_tender_view(("director",
 * "sourcing"), company)` (tender.py:2551), wider than the board's on purpose —
 * its own comment says so ("the gate covers both windows; the narrower one
 * would mean the board 403s while the funnel embedded in it leaks the same
 * number"). A sourcing-only user therefore CAN reach a working funnel; if it
 * were left outside the gate, that same user would see a live funnel sitting
 * above nothing — the "refusal, not an empty board" promise kept for the
 * table and broken one component up.
 *
 * DOM-less: source-regex for the gate and the panel (TEMPLATE, like every
 * other spec here), new-Function-lifted for load()'s request-suppression
 * behaviour (per contractBoardReload.spec.js's precedent).
 */

function liftLoad(scope) {
	const fn = src.match(/^async function load\(\)[\s\S]*?^\}/m);
	expect(fn, "DirectorBoard.vue has no top-level load()").not.toBeNull();
	const keys = Object.keys(scope);
	return new Function(...keys, `${fn[0]}\nreturn load;`)(...keys.map((k) => scope[k]));
}

async function flush(n = 4) {
	for (let i = 0; i < n; i++) await Promise.resolve();
}

function baseScope(views) {
	return {
		activeCompany: { value: "A" },
		data: { value: { rows: [], kpi: {}, currency: "" } },
		loading: { value: false },
		error: { value: "" },
		everLoaded: { value: false },
		canDirector: { value: views.includes("director") },
		session: { ensureTenderViews: () => Promise.resolve(views) },
		t: (s) => s,
	};
}

describe("P11 — the gate itself", () => {
	it("canDirector reads exactly the view tender_director_board requires", () => {
		// WHAT WOULD MAKE THIS FAIL: gating on anything but "director" — e.g.
		// widening it to match tender_funnel's own ("director" or "sourcing")
		// gate, which would let a sourcing-only user past a board the server
		// itself refuses them with _require_tender_view("director", company).
		expect(src).toMatch(/const canDirector = computed\(\(\) => session\.tenderViews\.includes\("director"\)\);/);
	});

	it("forbidden waits for tenderViews to have actually loaded", () => {
		// WHAT WOULD MAKE THIS FAIL: `forbidden = computed(() =>
		// !canDirector.value)` alone. Before ensureTenderViews() resolves,
		// tenderViews is still its initial [] and canDirector is false for
		// EVERY user, director included — that formula would flash the refusal
		// panel on every load, not just a real one.
		expect(src).toMatch(
			/const forbidden = computed\(\(\) => session\.tenderViewsLoaded && !canDirector\.value\);/
		);
	});
});

describe("P11 — load() sends zero requests to a user the server would refuse anyway", () => {
	it("never calls call() when canDirector is false", async () => {
		// WHAT WOULD MAKE THIS FAIL: removing `if (!canDirector.value) return;`
		// from load() — the request still fires, the server still 403s it, and
		// the client is back to P10's toast-then-silence for this one case that
		// a client-side gate could have avoided outright.
		let calls = 0;
		const scope = { ...baseScope(["sourcing"]), call: () => { calls += 1; return Promise.resolve({}); } };
		const load = liftLoad(scope);
		await load();
		await flush();
		expect(calls).toBe(0);
	});

	it("loads normally once canDirector is true", async () => {
		// WHAT WOULD MAKE THIS FAIL: a gate that is inverted or over-eager —
		// e.g. `if (canDirector.value) return;` — which would silently break
		// the board for every director while this file's other tests (built
		// against a canDirector: true harness) kept passing for the wrong
		// reason.
		let calls = 0;
		const scope = { ...baseScope(["director"]), call: () => { calls += 1; return Promise.resolve({ rows: [], kpi: {}, generated_at: "" }); } };
		const load = liftLoad(scope);
		await load();
		expect(calls).toBe(1);
	});
});

describe("P11 — a refusal, not an empty board", () => {
	it("the KPI strip, funnel and table all sit behind v-if=\"!forbidden\"", () => {
		// WHAT WOULD MAKE THIS FAIL: gating only the table (leaving the KPI
		// strip outside) — a non-director would then see six counters reading
		// zero, which is exactly the "empty board" the doc says is worse than
		// no board, just with the table itself hidden.
		const gateAt = TEMPLATE.indexOf('<template v-if="!forbidden">');
		expect(gateAt, 'no <template v-if="!forbidden"> wrapper found').toBeGreaterThan(-1);

		const kpisAt = TEMPLATE.indexOf('class="ds-kpis"');
		const funnelAt = TEMPLATE.indexOf("<TenderFunnel");
		const portfolioAt = TEMPLATE.indexOf('class="ds-panel board-portfolio"');
		expect(kpisAt, "ds-kpis not found").toBeGreaterThan(gateAt);
		expect(funnelAt, "TenderFunnel not found").toBeGreaterThan(gateAt);
		expect(portfolioAt, "board-portfolio not found").toBeGreaterThan(gateAt);

		const elseAt = TEMPLATE.indexOf('<section v-else class="ds-panel board-forbidden">');
		expect(elseAt, "no v-else board-forbidden panel found").toBeGreaterThan(-1);
		// everything gated sits BEFORE the v-else panel, i.e. inside the
		// v-if branch, not spilling past it into shared markup.
		expect(elseAt).toBeGreaterThan(kpisAt);
		expect(elseAt).toBeGreaterThan(funnelAt);
		expect(elseAt).toBeGreaterThan(portfolioAt);
	});

	it("the refusal panel reuses the operations-desk copy, plus exactly one new sentence", () => {
		// WHAT WOULD MAKE THIS FAIL: inventing new copy for the h2 or the link
		// instead of reusing TenderOverview.vue's already-translated keys (the
		// doc's own instruction — "cite prompt 15 §2 rather than designing this
		// twice"), or adding more than the one new key this row actually needs.
		const elseAt = TEMPLATE.indexOf('<section v-else class="ds-panel board-forbidden">');
		const panelEnd = TEMPLATE.indexOf("</section>", elseAt);
		expect(panelEnd, "board-forbidden section has no closing tag").toBeGreaterThan(elseAt);
		const panel = TEMPLATE.slice(elseAt, panelEnd);

		expect(panel.includes('t("Your work is on the operations desk")')).toBe(true);
		expect(panel.includes('t("Operations desk →")')).toBe(true);
		expect(panel).toMatch(/router\.push\(['"]\/tender\/desk['"]\)/);
		expect(
			panel.includes(
				't("This board is built for the director role. Your queue for today is on the operations desk.")'
			)
		).toBe(true);

		const tCalls = panel.match(/t\(/g) ?? [];
		expect(tCalls.length, "expected exactly 3 t() calls in the panel").toBe(3);
	});
});
