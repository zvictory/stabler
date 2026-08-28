import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/inventory/Items.vue"), "utf8");

const editRow = () => {
	const m = src.match(/async function openEditRow[\s\S]*?\n}/);
	expect(m, "openEditRow should exist").toBeTruthy();
	return m[0];
};

/**
 * `3000476` shipped a row Edit button bound to a function that did not exist, so
 * the click threw and the row simply stayed as it was — no modal, no error, no
 * trace outside the console. `bb88b16` bound it to a real function. What it did
 * not do is give the failing half of that function anything to say.
 *
 * Source assertions rather than a mounted component: `@vue/test-utils` is not a
 * dependency here. Each one pins a specific string whose removal is the bug.
 */
describe("editing an item straight from the list row", () => {
	it("tells the user when the row could not be loaded", () => {
		// `openEdit` builds its form out of `detail`, so the record is fetched
		// first. When that fetch fails, `detail.error` is set and the modal is
		// correctly not opened — and until this test, that was the whole of it:
		// the drawer was closed again on the way out and the click produced
		// nothing at all. From the floor that is indistinguishable from the dead
		// button `bb88b16` was written to fix, which is why it needs to be said
		// out loud rather than merely not-crashed-on.
		expect(editRow()).toMatch(/toast\.error\(/);
		expect(src).toMatch(/useToast/);
	});

	it("does not flash the detail drawer on the way to the edit modal", () => {
		// `openDetail` opens the drawer synchronously, before its await. Routed
		// through it, a click on Edit put the detail panel on screen for the
		// length of the network call and then closed it again — a panel the user
		// never asked for, covering the list they clicked from.
		expect(editRow()).toMatch(/openDetail\(row\.name, false\)/);
		expect(src).toMatch(/async function openDetail\(name, showDrawer = true\)/);
	});
});
