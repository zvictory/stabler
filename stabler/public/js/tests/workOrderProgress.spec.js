import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

vi.mock("../composables/i18n.js", () => ({ t: (s) => s }));
const { workOrderProgress } = await import("../composables/workOrderProgress.js");

describe("workOrderProgress", () => {
	it("answers how far along the order is", () => {
		const p = workOrderProgress({ qty: 4000, produced_qty: 2640, transferred_qty: 4000 });

		expect(p.donePct).toBe(66);
		expect(p.barPct).toBe(66);
	});

	// The three columns this replaces were Plan / Transferred / Produced. Two of
	// them collapse into "2 640 / 4 000" naturally; the third does not, and it is
	// the one that answers a different question — not "how far along" but "can
	// this order be worked at all". An order with nothing in WIP is not 0% done,
	// it is not started, and the shift supervisor needs to tell those apart from
	// across the room. Losing it would make the new column shorter and worse.
	it("keeps the transferred figure the old columns carried", () => {
		const p = workOrderProgress({ qty: 1200, produced_qty: 0, transferred_qty: 0 });

		expect(p.transferredPct).toBe(0);
		expect(p.nothingTransferred).toBe(true);
	});

	it("does not call a part-transferred order un-started", () => {
		const p = workOrderProgress({ qty: 1200, produced_qty: 0, transferred_qty: 600 });

		expect(p.transferredPct).toBe(50);
		expect(p.nothingTransferred).toBe(false);
	});

	it("survives an order with no quantity", () => {
		const p = workOrderProgress({ qty: 0, produced_qty: 0, transferred_qty: 0 });

		expect(p.donePct).toBe(0);
		expect(p.barPct).toBe(0);
		expect(Number.isFinite(p.donePct)).toBe(true);
	});

	// Over-production is real — ERPNext allows it, and the deviation panel exists
	// because it happens. The number must tell the truth; only the bar is clamped,
	// because a bar wider than its track is a rendering bug, not information.
	it("reports over-production honestly and still draws a sane bar", () => {
		const p = workOrderProgress({ qty: 100, produced_qty: 130, transferred_qty: 100 });

		expect(p.donePct).toBe(130);
		expect(p.barPct).toBe(100);
	});

	it("treats missing figures as zero rather than NaN", () => {
		const p = workOrderProgress({ qty: 500 });

		expect(p.donePct).toBe(0);
		expect(p.nothingTransferred).toBe(true);
	});
});

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/manufacturing/WorkOrders.vue"), "utf8");

describe("the work order list table", () => {
	// The header row of the LIST table only — the detail drawer keeps its own
	// Planned / Transferred / Produced read-out, where there is room for three
	// figures and no twenty rows to scan.
	const listHead = src.slice(src.indexOf("<thead>"), src.indexOf("</thead>"));

	it("carries one progress column instead of three number columns", () => {
		expect(src).toMatch(/workOrderProgress/);
		expect(listHead).toMatch(/t\("Progress"\)/);
		for (const gone of ["Planned", "Transferred", "Produced"]) {
			expect(listHead, `list header still has a ${gone} column`).not.toMatch(
				new RegExp(`t\\("${gone}"\\)`),
			);
		}
	});

	it("keeps produced and planned readable as a ratio, not as one number", () => {
		expect(src).toMatch(/formatQty\(r\.produced_qty\)/);
		expect(src).toMatch(/formatQty\(r\.qty\)/);
	});

	it("says so when nothing has been transferred", () => {
		expect(src).toMatch(/nothingTransferred/);
		expect(src).toContain("materials not transferred");
	});
});
