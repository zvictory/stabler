import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

vi.mock("../composables/i18n.js", () => ({ t: (s) => s }));

const here = dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(resolve(here, rel), "utf8");
const list = read("../pages/manufacturing/WorkOrders.vue");
const detail = read("../pages/manufacturing/WorkOrderDetail.vue");
const router = read("../router.js");

describe("the work order detail is a page, not a drawer", () => {
	// A 700px panel sliding over the list is the wrong shape for what people do
	// with an order: it is read on a tablet on the floor, its link is sent to
	// whoever has to answer for a shortage, and its material table is twelve
	// columns wide. A URL, browser back and the full width fix all three.
	it("is addressable by URL", () => {
		expect(router).toMatch(/path: "work-orders\/:name"/);
		expect(router).toMatch(/name: "manufacturing-work-order"/);
	});

	it("is what a row in the list opens", () => {
		expect(list).toMatch(/manufacturing-work-order/);
	});

	// Two homes for the same detail drift — this repository has the four
	// divergent copies of .rsync-exclude to prove it. The drawer does not stay
	// behind "just in case".
	it("leaves no second copy behind in the list", () => {
		expect(list).not.toMatch(/offcanvas/);
		expect(list).not.toMatch(/detailOpen/);
	});

	// The bulk gesture stays on the list, where a selection exists.
	it("keeps whole-selection assignment on the list", () => {
		expect(list).toMatch(/assign_work_order_operators_bulk/);
		expect(detail).not.toMatch(/assign_work_order_operators_bulk/);
	});

	// One picker, one endpoint, one "— Remove operator —" entry. Two pages need
	// it now, and keeping two copies in step by hand is how they stop matching.
	it("shares one operator picker between the two pages", () => {
		for (const src of [list, detail]) {
			expect(src).toMatch(/useOperatorOptions/);
			expect(src).not.toMatch(/operatorSelectOptions = computed/);
		}
	});
});

describe("stage cards", () => {
	// Measured on the only tenant that runs work orders: 4 211 orders, 560 BOMs,
	// zero Work Order Operation rows, zero Workstations. Cards per routing
	// operation would be an empty grid on every order in the system; cards per
	// role are the decomposition the floor actually has.
	it("are built from the roles, not from routing operations", () => {
		expect(detail).toMatch(/workOrderStages/);
		expect(detail).toMatch(/v-for="s in stages"/);
	});

	it("name the person answerable for each stage", () => {
		expect(detail).toMatch(/s\.operator/);
		expect(detail).toMatch(/not assigned/);
	});

	// An unowned material is the one that needs saying out loud, and the card
	// for it is the only place on the page that says so.
	it("mark the stage nobody owns", () => {
		expect(detail).toMatch(/s\.role \? roleLabel\(s\.role\) : t\("undecided"\)/);
	});
});
