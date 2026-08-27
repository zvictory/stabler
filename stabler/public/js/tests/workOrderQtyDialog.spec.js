import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

vi.mock("../composables/i18n.js", () => ({ t: (s) => s }));

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/manufacturing/WorkOrders.vue"), "utf8");

// Issuing materials and booking production were the last two actions in the SPA
// that asked for a number through the browser's bare `prompt()`. That box can
// render exactly one line of text: it cannot show which materials the number
// consumes, how much of each is on the shelf, or that one of them will run out
// halfway. The operator typed a quantity and found out afterwards.
describe("work order quantity dialog", () => {
	it("no longer asks for the quantity through a bare browser prompt", () => {
		expect(src).not.toMatch(/\bprompt\(/);
	});

	// The point of the replacement is the list, not the box. A dialog that only
	// moved the same single input into nicer markup would be a reskin.
	it("shows what the typed quantity takes off the shelves", () => {
		expect(src).toMatch(/materialsForUnits/);
		expect(src).toMatch(/v-for="m in dialogMaterials"/);
		expect(src).toMatch(/m\.needed/);
		expect(src).toMatch(/m\.available/);
	});

	// The figures have to follow the box as it is typed in. If the list were
	// computed once when the dialog opened, changing 4000 to 500 would leave a
	// material list describing a transfer that is not the one about to happen —
	// worse than no list, because it looks checked.
	it("recomputes the list from the quantity being typed", () => {
		expect(src).toMatch(/const dialogUnits = computed\(/);
		expect(src).toMatch(/materialsForUnits\([^)]*dialogUnits\.value\)/);
	});

	// A shortage the operator can see before committing is the whole reason the
	// stock figures were joined onto this screen.
	it("marks the lines the store cannot cover", () => {
		expect(src).toMatch(/m\.short/);
	});

	// Both actions keep their own arithmetic: transfer counts against what has
	// been issued, production against what has been finished. Defaulting both to
	// the order quantity would offer to re-transfer material already in WIP.
	it("defaults each action to its own outstanding balance", () => {
		expect(src).toMatch(/produced_qty/);
		expect(src).toMatch(/transferred_qty/);
		expect(src).toMatch(/const dialogBalance = computed\(/);
	});

	it("still posts the two distinct stock entry purposes", () => {
		expect(src).toMatch(/Material Transfer for Manufacture/);
		expect(src).toMatch(/"Manufacture"/);
	});
});
