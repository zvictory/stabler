import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick, reactive } from "vue";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));

/** The file with every comment blanked out — line count and numbering preserved. */
function withoutComments(src) {
	const blank = (m) => m.replace(/[^\n]/g, " ");
	return src
		.replace(/<!--[\s\S]*?-->/g, blank)
		.replace(/\/\*[\s\S]*?\*\//g, blank)
		.split("\n")
		.map((line) => (/^\s*\/\//.test(line) ? "" : line))
		.join("\n");
}

/**
 * `useListViewState` documents itself as "URL = source of truth" and then reads
 * the URL exactly once, in onMounted. So a query change that does NOT remount
 * the component — an address-bar edit, a pasted deep link, a same-route
 * navigation — moved the URL and left the screen showing the previous record.
 *
 * Measured 2026-09-03 on mikas: with the supplier pane open on Yiwu Humo,
 * navigating to `?c="Advanced Screening Technologies" Mchj` changed the address
 * bar and the panel kept showing Yiwu Humo. A link one colleague sends another
 * therefore opens the wrong supplier for anyone who already had the page open —
 * and the URL says otherwise, so nobody suspects it.
 *
 * These run the composable for real (no DOM, no component mount — see
 * vitest.config.mjs: environment "node"). `onMounted` is stubbed to fire
 * immediately, which is what a mount does; the router mock writes the query
 * back the way vue-router does, so the state -> URL -> state cycle is exercised
 * rather than assumed.
 */

const route = reactive({ path: "/purchasing/suppliers", query: {} });
const replace = vi.fn((to) => {
	route.query = { ...(to.query || {}) };
});

vi.mock("vue-router", () => ({
	useRoute: () => route,
	useRouter: () => ({ replace }),
}));

vi.mock("vue", async (importOriginal) => {
	const actual = await importOriginal();
	// A mount runs these synchronously; outside a component Vue would drop them
	// and the composable would never leave its un-hydrated state.
	return { ...actual, onMounted: (fn) => fn() };
});

const { useListViewState } = await import("../composables/useListViewState.js");

// The composable writes through to localStorage, which node does not have. Its
// own try/catch would swallow the ReferenceError, but then the test would be
// asserting against an exception path instead of the storage the code thinks it
// is using — and the stored value is what mount-time hydration reads.
const store = new Map();
globalThis.localStorage = {
	getItem: (k) => (store.has(k) ? store.get(k) : null),
	setItem: (k, v) => store.set(k, String(v)),
	removeItem: (k) => store.delete(k),
};

const SCHEMA = { search: "", sortField: "name", sortAsc: true, c: "" };

beforeEach(() => {
	store.clear();
	replace.mockClear();
	route.path = "/purchasing/suppliers";
	route.query = {};
});

describe("useListViewState follows the URL after mount, not only at it", () => {
	it("adopts a record that appears in the query while the page is already open", async () => {
		// WHAT WOULD MAKE THIS FAIL: reading route.query only in onMounted. This is
		// the reported defect — the address bar says one supplier and the pane shows
		// another. Silent in both directions: no error, no empty state, just the
		// wrong record under a URL that names the right one.
		const { c } = useListViewState("stabler.suppliers.listState", SCHEMA);
		expect(c.value).toBe("");

		route.query = { c: "ACME" };
		await nextTick();

		expect(c.value).toBe("ACME");
	});

	it("returns a key to its default when the query drops it", async () => {
		// WHAT WOULD MAKE THIS FAIL: applying only the keys present in the incoming
		// query. buildQuery DELETES a key that sits at its default, so an absent key
		// does not mean "unspecified" here — it means "default", and that is the
		// only reading under which the URL is a full description of the state. Get
		// this wrong and going from `?c=ACME` back to the bare list URL leaves ACME
		// selected under a URL that no longer mentions it.
		route.query = { c: "ACME" };
		const { c } = useListViewState("stabler.suppliers.listState", SCHEMA);
		expect(c.value).toBe("ACME");

		route.query = {};
		await nextTick();

		expect(c.value).toBe("");
	});

	it("coerces through the schema rather than pasting raw strings in", async () => {
		// WHAT WOULD MAKE THIS FAIL: assigning q[key] directly. Every query value is
		// a string, so `sortAsc` would become "0" — which is truthy — and the list
		// would sort ascending while the URL and the arrow both say descending.
		const { sortAsc } = useListViewState("stabler.suppliers.listState", SCHEMA);
		route.query = { sortAsc: "0" };
		await nextTick();

		expect(sortAsc.value).toBe(false);
	});
});

describe("it lets go when the page it belongs to is being left", () => {
	it("ignores a query that belongs to a different route", async () => {
		// WHAT WOULD MAKE THIS FAIL: watching route.query without checking the path.
		// This is the hazard the fix introduces if written carelessly, and it is
		// reachable from the screen being fixed: Suppliers.vue pushes to
		// /tender/sourcing?deal=… from a quotation row. On that navigation the
		// departing component still sees the watcher fire, would reset every key to
		// its default, and the resulting router.replace would rewrite the query of
		// the page the user just arrived at. A stale pane is a bug; corrupting the
		// destination's URL is a worse one.
		const { c } = useListViewState("stabler.suppliers.listState", SCHEMA);
		route.query = { c: "ACME" };
		await nextTick();
		expect(c.value).toBe("ACME");

		replace.mockClear();
		route.path = "/tender/sourcing";
		route.query = { deal: "CRM-DEAL-2026-00107" };
		await nextTick();

		expect(c.value, "the departing page rewrote its own state").toBe("ACME");
		expect(replace, "the departing page wrote to the new route's URL").not.toHaveBeenCalled();
	});
});

/**
 * The other half. The composable now moves `c` when the URL moves, but PartyCenter
 * resolved that name into a row exactly once, in its own onMounted — so a moved
 * `c` would update the address bar and the localStorage and still leave the old
 * party in the pane.
 *
 * Wiring assertions, not behaviour: PartyCenter is an SFC and this suite mounts
 * no components (vitest.config.mjs, environment "node"). They catch the watcher
 * being deleted or rewritten without its re-entry guard — which is the regression
 * that costs four network calls per selection and can loop.
 */
const partyCenter = readFileSync(resolve(here, "../components/party/PartyCenter.vue"), "utf8");

function partyCenterWatchBody() {
	const src = withoutComments(partyCenter);
	const at = src.indexOf("watch(selectedName");
	expect(at, "PartyCenter no longer reacts to the URL's party name").toBeGreaterThan(-1);
	const end = src.indexOf("\n});", at);
	expect(end, "the watch never closes").toBeGreaterThan(at);
	return src.slice(at, end);
}

describe("PartyCenter acts on a party name that changed under it", () => {
	it("re-enters selection through the list, not a second copy of selectRow", () => {
		// WHAT WOULD MAKE THIS FAIL: inlining the four loaders here. selectRow
		// already owns that sequence AND writes selectedName back; a copy would
		// drift from it the first time selection grows a step, which is how the
		// ledger date reset came to exist in one path and not the other.
		const body = partyCenterWatchBody();
		expect(body).toMatch(/byName\.value\[name\]/);
		expect(body).toMatch(/selectRow\(/);
	});

	it("returns early when the name is one it set itself", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping the guard. selectRow assigns
		// selectedName, so every ordinary click would re-enter this watch and fire
		// loadLedger/loadOrders/loadQuotes/loadDetail a second time for the row
		// already open — four requests per click, and a loop if selectRow ever
		// stops being idempotent.
		expect(partyCenterWatchBody()).toMatch(/if \(name === \(selected\.value\?\.name \|\| ""\)\) return;/);
	});

	it("clears the pane rather than leaving a party the URL no longer names", () => {
		// WHAT WOULD MAKE THIS FAIL: doing nothing when the name is empty or absent
		// from the loaded list. Then the URL would say one thing and the pane
		// another — the exact defect this whole file exists for, just reached from
		// the other direction. Mount already treats an unresolvable deep link this
		// way: no selection, cockpit visible.
		const body = partyCenterWatchBody();
		expect(body).toMatch(/selected\.value = null;/);
		expect(body).toMatch(/emit\("select", null\);/);
	});
});

/**
 * Employees is the composable's third consumer and resolves `c` in its own
 * onMounted, exactly as PartyCenter did. Left alone it would be the trap this
 * change creates rather than one it inherits: the composable now documents the
 * URL as live, so the next reader would assume this screen follows it.
 */
const employees = readFileSync(resolve(here, "../pages/hr/Employees.vue"), "utf8");

function employeesWatchBody() {
	const src = withoutComments(employees);
	const at = src.indexOf("watch(selectedName");
	expect(at, "Employees no longer reacts to the URL's employee name").toBeGreaterThan(-1);
	const end = src.indexOf("\n});", at);
	expect(end, "the watch never closes").toBeGreaterThan(at);
	return src.slice(at, end);
}

describe("Employees follows the same URL as its composable", () => {
	it("resolves the name against the loaded rows and opens it", () => {
		// WHAT WOULD MAKE THIS FAIL: moving the ref without opening the record —
		// which is worse than doing nothing, because the URL, localStorage and the
		// pane would then hold three different opinions instead of two.
		const body = employeesWatchBody();
		expect(body).toMatch(/rows\.value\.find\(/);
		expect(body).toMatch(/select\(/);
	});

	it("returns early when the name is one it set itself", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping the guard. select() assigns
		// selectedName, so an ordinary click would re-enter and re-run the finance
		// load for the employee already open.
		expect(employeesWatchBody()).toMatch(/if \(name === \(selected\.value\?\.name \|\| ""\)\) return;/);
	});

	it("empties the pane when the name resolves to nothing", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving the previous employee on screen under
		// a URL that names someone else — the reported defect, on this screen.
		const body = employeesWatchBody();
		expect(body).toMatch(/selected\.value = null;/);
		expect(body).toMatch(/fin\.value = null;/);
	});
});
