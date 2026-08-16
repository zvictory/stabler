import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const pagePath = resolve(here, "../pages/installment/Agreements.vue");
const drawerPath = resolve(here, "../components/AgreementPreviewDrawer.vue");
const src = readFileSync(pagePath, "utf8");
const drawerSrc = readFileSync(drawerPath, "utf8");

/**
 * Execute a `function <name>(...) { ... }` or `const <name> = computed(() => {…})`
 * straight out of the shipped SFC source.
 *
 * @vue/test-utils is not a devDependency of this repo, so mounting the page is
 * not available (see installmentOperations.spec.js for the same constraint).
 * Running the real source beats asserting on source text: a `toContain("sort")`
 * check passes for a sort that sorts backwards, and every behaviour below is one
 * a string match would wave through.
 */
function extractFunction(name, args, deps) {
	const marker = `function ${name}(`;
	const start = src.indexOf(marker);
	expect(start, `${name} not found in Agreements.vue`).toBeGreaterThan(-1);
	const bodyStart = src.indexOf("{", start) + 1;
	const end = src.indexOf("\n}", bodyStart);
	expect(end, `${name} has no closing brace at column 0`).toBeGreaterThan(bodyStart);
	const body = src.slice(bodyStart, end);
	const fn = new Function(...args, ...Object.keys(deps), body); /* eslint-disable-line no-new-func */
	return (...callArgs) => fn(...callArgs, ...Object.values(deps));
}

function extractComputed(name, deps) {
	const marker = `const ${name} = computed(() => {`;
	const start = src.indexOf(marker);
	expect(start, `${name} not found in Agreements.vue`).toBeGreaterThan(-1);
	const bodyStart = start + marker.length;
	const end = src.indexOf("\n});", bodyStart);
	expect(end, `${name} has no closing '});'`).toBeGreaterThan(bodyStart);
	const body = src.slice(bodyStart, end);
	const fn = new Function(...Object.keys(deps), body); /* eslint-disable-line no-new-func */
	return fn(...Object.values(deps));
}

// Interpolating stub: t("restructured {n} times", { n: 4 }) -> "restructured 4 times".
const t = (source, params) =>
	params ? String(source).replace(/\{(\w+)\}/g, (_, k) => params[k]) : source;

const chainLabel = extractFunction("chainLabel", ["row"], { t });
const showsPartial = extractFunction("showsPartial", ["row"], {});

describe("Agreements.vue — the restructure chain badge (stabler-vjfd / the ADR's condition)", () => {
	it("says nothing at all about an agreement that was never restructured", () => {
		// The common case. A badge that fires on every row carries no information,
		// and the backend reports 1/1 for every ordinary agreement — so the guard
		// here is what keeps "restructured" meaningful when it does appear.
		for (const row of [
			{ chain_length: 1, chain_position: 1, restructure_count: 0 },
			{}, // agreement_list from an older bundle, before the chain keys existed
			null,
		]) {
			expect(chainLabel(row)).toBe("");
		}
	});

	it("renders position and history together, so neither has to be looked up", () => {
		// This is the literal string the owner made a condition of their vote:
		// without it you go hunting for the last closed agreement to learn that
		// this contract has been renegotiated twice.
		expect(chainLabel({ chain_position: 3, chain_length: 3, restructure_count: 2 })).toBe(
			"3/3 · restructured twice"
		);
		expect(chainLabel({ chain_position: 1, chain_length: 3, restructure_count: 2 })).toBe(
			"1/3 · restructured twice"
		);
	});

	it("spells out the counts that actually occur and parameterises the rest", () => {
		expect(chainLabel({ chain_position: 2, chain_length: 2, restructure_count: 1 })).toBe(
			"2/2 · restructured once"
		);
		// "restructured 1 times" is not a sentence in any of the five languages
		// this app ships, which is why once/twice are separate keys at all.
		expect(chainLabel({ chain_position: 4, chain_length: 4, restructure_count: 3 })).toBe(
			"4/4 · restructured 3 times"
		);
	});
});

describe("Agreements.vue — Partial as a secondary badge", () => {
	it("surfaces part-payment on an overdue agreement, which the payment state hides", () => {
		// read.py:103-110 derives payment_state exclusively and in order, so an
		// overdue agreement that has already paid something reports "Overdue" and
		// never "Partial". Money already collected changes how you talk to the
		// customer, so it needs to survive that collapse.
		expect(showsPartial({ payment_state: "Overdue", paid: 400, outstanding: 600 })).toBe(true);
	});

	it("does not print the same word twice in one cell", () => {
		expect(showsPartial({ payment_state: "Partial", paid: 400, outstanding: 600 })).toBe(false);
	});

	it("stays silent when nothing has been paid or nothing is left", () => {
		expect(showsPartial({ payment_state: "Overdue", paid: 0, outstanding: 1000 })).toBe(false);
		expect(showsPartial({ payment_state: "Paid", paid: 1000, outstanding: 0 })).toBe(false);
		expect(showsPartial({ payment_state: "Not Started", paid: 0, outstanding: 1000 })).toBe(false);
	});
});

describe("Agreements.vue — per-currency totals", () => {
	const user = { value: { language: "en" } };
	const formatMoney = (amt, curr) => `${curr} ${amt}`;

	function totalsFor(totals_by_currency) {
		return extractComputed("agrTotals", {
			listing: { value: { totals_by_currency } },
			formatMoney,
			t: (s) => s,
			user,
		});
	}

	it("puts the largest outstanding exposure first, whatever order the payload arrived in", () => {
		// KpiCard promotes lines[0] to the hero value, so this ordering decides
		// which currency becomes the headline. Drop the sort and a 400 USD
		// exposure can outrank a 900,000,000 UZS one purely on serialisation order.
		const buckets = totalsFor({
			USD: { total: 500, paid: 100, outstanding: 400 },
			UZS: { total: 1_000_000_000, paid: 100_000_000, outstanding: 900_000_000 },
		});
		expect(buckets.map((b) => b.currency)).toEqual(["UZS", "USD"]);
	});

	it("keeps every currency in its own bucket and never adds them together", () => {
		// One agreement carries one currency. A summed total is not money.
		const buckets = totalsFor({
			USD: { total: 500, paid: 100, outstanding: 400 },
			UZS: { total: 900, paid: 200, outstanding: 700 },
		});
		expect(buckets).toHaveLength(2);
		const usd = buckets.find((b) => b.currency === "USD");
		expect(usd.lines[0]).toBe("USD 400");
		expect(usd.lines.join(" ")).not.toContain("UZS");
	});

	it("is empty before the first response, so the header renders nothing", () => {
		expect(totalsFor(undefined)).toEqual([]);
		expect(totalsFor({})).toEqual([]);
	});
});

describe("Agreements.vue / AgreementPreviewDrawer.vue — repository rules", () => {
	it("never links out to the Frappe Desk", () => {
		expect(src).not.toContain("/app/");
		expect(drawerSrc).not.toContain("/app/");
	});

	it("resolves every status badge centrally instead of mapping colours per page", () => {
		expect(src).toContain('import StatusBadge from "../../components/StatusBadge.vue";');
		expect(src).toContain('doctype="Vehicle Finance Payment Health"');
		expect(drawerSrc).toContain('doctype="Vehicle Finance Payment Health"');
	});

	it("uses the shared list furniture rather than hand-rolled toolbars and spinners", () => {
		expect(src).toContain('import ListToolbar from "../../components/ListToolbar.vue";');
		expect(src).toContain("<SkeletonRows");
		expect(src).not.toContain("table-striped");
		// Auto-apply filtering: no Apply/Refresh button anywhere on the page.
		expect(src).not.toMatch(/t\(["']Apply["']\)/);
	});

	it("reads the list from agreement_list and the drawer rows from agreement_detail", () => {
		expect(src).toContain("stabler.api.vehicle_finance.read.agreement_list");
		expect(src).toContain("stabler.api.vehicle_finance.read.agreement_detail");
	});

	it("keeps the drawer read-only — no money moves from a preview", () => {
		// Drawers are read-only by design: every money movement happens on a full
		// page, so a mis-click while skim-reading a list cannot collect against
		// the wrong agreement.
		expect(drawerSrc).toContain('t("Read only")');
		for (const mutation of ["collect_customer_payment", "pay_supplier", "cancel_payment", "record_promise"]) {
			expect(drawerSrc).not.toContain(mutation);
		}
	});

	it("hides both open-agreement actions until the agreement page exists", () => {
		// Slice stabler-l0m.3.10 registers `vf-agreement-detail`. Asking the router
		// rather than hardcoding means this page cannot ship a link that goes
		// nowhere, and the buttons appear on their own once that route lands.
		expect(src).toContain('router.hasRoute("vf-agreement-detail")');
		expect(src).toContain('v-if="canOpenAgreement"');
		expect(drawerSrc).toContain('v-if="canOpenAgreement"');
	});
});
