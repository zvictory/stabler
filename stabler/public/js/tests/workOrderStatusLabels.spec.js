import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/manufacturing/WorkOrders.vue"), "utf8");
const detail = readFileSync(resolve(here, "../pages/manufacturing/WorkOrderDetail.vue"), "utf8");
const shared = readFileSync(resolve(here, "../composables/workOrderStatus.js"), "utf8");

/** The raw ERPNext statuses the screen filters by, as declared in the SFC. */
function declaredStatuses() {
	const m = shared.match(/WORK_ORDER_STATUSES = \[([^\]]*)\]/);
	expect(m, "WORK_ORDER_STATUSES").toBeTruthy();
	return [...m[1].matchAll(/"([^"]*)"/g)].map((x) => x[1]).filter(Boolean);
}

/** The status → label map, as declared in the SFC. */
function labelMap() {
	const m = shared.match(/statusLabels = computed\(\(\) => \(\{([\s\S]*?)\}\)\);/);
	expect(m, "const statusLabels").toBeTruthy();
	const out = {};
	for (const line of m[1].split("\n")) {
		const e = line.match(/^\s*"?([^":]+?)"?\s*:\s*(.+?),\s*$/);
		if (e) out[e[1]] = e[2];
	}
	return out;
}

describe("work order status labels", () => {
	// The screen prints whatever ERPNext stores, and ERPNext stores English.
	// A Russian-speaking shop supervisor reads "In Process" in a column whose
	// header is translated — the one word that tells them what to do next is
	// the one word left in a language they may not read.
	it("gives every filterable status a label", () => {
		const missing = declaredStatuses().filter((s) => !(s in labelMap()));

		expect(missing, "statuses with no entry in statusLabels").toEqual([]);
	});

	// The guard that matters over time: adding a status to STATUSES and
	// forgetting the label falls back to the raw English silently, which is
	// exactly the defect being fixed. This test is the thing that notices.
	it("labels nothing it cannot filter by", () => {
		const extra = Object.keys(labelMap()).filter((k) => !declaredStatuses().includes(k));

		expect(extra, "labels for statuses not in STATUSES").toEqual([]);
	});

	it("routes every label through t() so the harvester can find the key", () => {
		const raw = Object.entries(labelMap()).filter(([, v]) => !v.startsWith("t("));

		expect(raw, "labels that are not t(\"...\") calls").toEqual([]);
	});

	it("prints the label in the table, not the stored value", () => {
		expect(src).not.toMatch(/\{\{\s*r\.status\s*\}\}/);
		expect(src).toMatch(/statusLabel\(r\.status\)/);
	});

	it("prints the label in the filter dropdown too", () => {
		const m = shared.match(/statusOptions = computed\([\s\S]*?\);/);

		expect(m, "const statusOptions").toBeTruthy();
		expect(m[0]).toMatch(/statusLabel\(/);
	});
});

// The list and the detail page each grew their own status→colour map, and they
// disagreed: a Draft order was yellow in the list and grey on its own page, a
// Cancelled one grey in the list and red on the page. Same order, same status,
// two answers depending on which screen you were standing in front of. Worse,
// the detail page printed the stored English straight through — the exact
// defect the list's labels were written to fix, reintroduced 42 minutes after
// they landed. So neither screen is allowed its own copy any more.
describe("one status vocabulary for both work order screens", () => {
	it("prints the label on the detail page, not the stored value", () => {
		expect(detail).not.toMatch(/\{\{\s*detail\??\.status\s*\}\}/);
		expect(detail).toMatch(/statusLabel\(/);
	});

	it("leaves neither page a status→colour map of its own", () => {
		// A local map is how the two drifted apart; the shared one is the only
		// place a colour may be decided.
		for (const [name, file] of [["the list", src], ["the detail page", detail]]) {
			expect(file, `${name} should not declare its own badge map`).not.toMatch(
				/const statusBadge = /,
			);
		}
	});

	it("resolves both badges through the central status map", () => {
		// `10-frontend.md`: status badges resolve through `getStatusBadgeClass`,
		// no per-page mappings.
		expect(src).toMatch(/statusBadge\(r\.status\)/);
		expect(detail).toMatch(/statusBadge\(detail\.status\)/);
		expect(shared).toMatch(/getStatusBadgeClass\("Work Order", /);
	});

	it("gives the central map an entry for every status the screens filter by", () => {
		const map = readFileSync(resolve(here, "../composables/status.js"), "utf8");
		const entry = map.match(/"Work Order": \{([\s\S]*?)\}/);
		expect(entry, 'STATUS_MAP["Work Order"]').toBeTruthy();
		const missing = declaredStatuses()
			.filter(Boolean)
			.filter((s) => !entry[1].includes(`"${s}"`) && !entry[1].includes(`${s}:`));
		expect(missing, "statuses with no colour in STATUS_MAP").toEqual([]);
	});
});
