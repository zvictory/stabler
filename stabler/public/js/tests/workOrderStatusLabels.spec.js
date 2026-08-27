import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/manufacturing/WorkOrders.vue"), "utf8");

/** The raw ERPNext statuses the screen filters by, as declared in the SFC. */
function declaredStatuses() {
	const m = src.match(/const STATUSES = \[([^\]]*)\]/);
	expect(m, "const STATUSES").toBeTruthy();
	return [...m[1].matchAll(/"([^"]*)"/g)].map((x) => x[1]).filter(Boolean);
}

/** The status → label map, as declared in the SFC. */
function labelMap() {
	const m = src.match(/const statusLabels = computed\(\(\) => \(\{([\s\S]*?)\}\)\);/);
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
		const m = src.match(/const statusOptions = computed\([\s\S]*?\);/);

		expect(m, "const statusOptions").toBeTruthy();
		expect(m[0]).toMatch(/statusLabel\(/);
	});
});
