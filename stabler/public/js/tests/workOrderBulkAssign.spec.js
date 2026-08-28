import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const list = readFileSync(resolve(here, "../pages/manufacturing/WorkOrders.vue"), "utf8");

/**
 * The list gets checkboxes and one bulk action, and both introduce a way to lie
 * to the user that the single-order flow did not have.
 *
 * These are source assertions rather than mounted-component assertions because
 * `@vue/test-utils` is not a dependency here — the same shape as
 * `remittanceMoneyGates.spec.js`. That buys less than a real mount, so each test
 * pins a specific string whose removal is the bug, not the general shape of the
 * markup.
 */
describe("bulk operator assignment", () => {
	it("does not open the detail panel when a row's checkbox is ticked", () => {
		// The <tr> carries @click="openDetail(r.name)". A checkbox inside it inherits
		// that click, so selecting five orders would open five detail panels and the
		// last one would cover the toolbar the selection was for.
		const cell = list.match(/<td[^>]*class="[^"]*wo-select[^"]*"[\s\S]*?<\/td>/);
		expect(cell, "the select cell should exist").toBeTruthy();
		expect(cell[0]).toMatch(/@click\.stop/);
	});

	it("keeps the bulk action disabled until something is selected", () => {
		// Otherwise the dialog opens on an empty selection and the backend's
		// "Select at least one Work Order" arrives as a red toast for a mistake the
		// button should not have allowed.
		//
		// Scoped to the toolbar button that opens the dialog, and not to the file:
		// the dialog's own Save button carries the same guard, so a file-wide match
		// stays green with the toolbar button wide open.
		const button = list.match(/<button[^>]*@click="openBulk"[\s\S]*?<\/button>|<button[\s\S]{0,400}?@click="openBulk"[\s\S]*?<\/button>/);
		expect(button, "the toolbar button should exist").toBeTruthy();
		expect(button[0]).toMatch(/:disabled="[^"]*!selected\.size[^"]*"/);
	});

	it("shows what the sweep refused, not only what it assigned", () => {
		// The endpoint returns {assigned, skipped} precisely so a partial result can
		// be told apart from a complete one. Rendering only the first half makes
		// "14 of 15" indistinguishable from "15 of 15".
		expect(list).toMatch(/bulkSkipped/);
		expect(list).toMatch(/v-for="s in bulkSkipped"/);
		expect(list).toMatch(/s\.reason/);
	});

	it("names the orders it refused, so they can be found again", () => {
		// A count alone ("3 skipped") leaves the manager to diff two lists by eye.
		expect(list).toMatch(/v-for="s in bulkSkipped"[\s\S]{0,400}s\.name/);
	});

	it("clears the selection only for the orders that were actually written", () => {
		// The refused ones stay ticked so the manager can act on the reason without
		// re-finding them in the list. Two halves to this: `assigned` drives the
		// removal, and nothing wipes the selection wholesale afterwards.
		expect(list).toMatch(/assigned\.forEach\([\s\S]{0,60}\.delete\(name\)/);
		const body = list.slice(list.indexOf("async function confirmBulk"));
		expect(body.slice(0, body.indexOf("\n}"))).not.toMatch(/selected\.value = new Set\(\)/);
	});

	it("shows the reason when the sweep fails outright", () => {
		// `bulkSkipped` covers the partial case: the call went through and the
		// backend named the orders it refused. It cannot cover the other one — the
		// operator list never loaded, or the whole write threw — because then there
		// is no per-order verdict to list and `bulkSkipped` stays empty. The code
		// writes that case into `actionError`, and a1d7516 deleted the only element
		// that rendered it along with the drawer it sat in: the dialog then stayed
		// open and unchanged with the button live again, so "assigned 15 orders"
		// and "assigned none of them" looked identical from the screen.
		expect(list).toMatch(/v-if="actionError"/);
		const body = list.match(/<div class="modal-body">[\s\S]*?<\/div>\s*<div class="modal-footer">/);
		expect(body, "the bulk dialog body should exist").toBeTruthy();
		expect(body[0]).toMatch(/actionError/);
	});

	it("does not greet the next attempt with the last one's error", () => {
		// The ref outlives the dialog. Opening it again on a stale red banner
		// reports a failure that did not happen this time.
		const open = list.slice(list.indexOf("function openBulk"));
		expect(open.slice(0, open.indexOf("\n}"))).toMatch(/actionError\.value = ""/);
	});

	it("sends only the roles the manager filled in", () => {
		// Bulk must not read an untouched box as "remove that operator" — the
		// backend defends this too, but a UI that posts "" for the empty half is
		// asking the backend to make a decision the manager never made.
		expect(list).toMatch(/bulkOperator\.value \|\| ""/);
		expect(list).toMatch(/bulkPackagingOperator\.value \|\| ""/);
	});
});

describe("role chips in the operator column", () => {
	it("labels each line with its role chip rather than a bare sentence", () => {
		const cell = list.match(/<td[^>]*class="[^"]*wo-operators[^"]*"[\s\S]*?<\/td>/);
		expect(cell, "the operators cell should exist").toBeTruthy();
		// Both chips come from the shared roleLabel, so the list, the kiosk and the
		// deviation footer cannot drift into three different words for one role.
		expect(cell[0]).toMatch(/roleLabel\("Production"\)/);
		expect(cell[0]).toMatch(/roleLabel\("Packaging"\)/);
	});

	it("still shows the empty half in red rather than as a dash", () => {
		// Unchanged from before the chips, and the reason is unchanged: a grey "—"
		// reads as "no data here", and this is a blocker on starting the order.
		const cell = list.match(/<td[^>]*class="[^"]*wo-operators[^"]*"[\s\S]*?<\/td>/);
		expect(cell[0]).toMatch(/text-danger/);
		expect(cell[0]).toMatch(/t\("not assigned"\)/);
	});
});
