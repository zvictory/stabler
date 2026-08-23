import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const SCREENS = {
	Expenses: readFileSync(resolve(here, "../pages/money/Expenses.vue"), "utf8"),
	Transfers: readFileSync(resolve(here, "../pages/money/Transfers.vue"), "utf8"),
};

/**
 * P0-MONEY-2, third half — once the editor was open, nothing in it said what
 * was being edited.
 *
 * A draft and a posted voucher rendered identically, and the heading called
 * both of them an amendment: `formTitle` read `editingName ? t("Amend expense")`
 * with no look at docstatus. The server does two different things behind that
 * one word (money.py:3516-3522) -- a submitted voucher is CANCELLED and a
 * replacement posted against `amended_from`, while a draft is DELETED outright
 * and re-created under a new name. Neither is what "amend" alone conveys, and
 * the one that touches the ledger deserved to be distinguishable from the one
 * that does not.
 *
 * The stale-badge trap is the reason for the second test. `editingDocstatus` is
 * only honest while it tracks `editingName`; leave one place that clears the
 * name without clearing the status and the next NEW entry renders wearing the
 * last-amended voucher's badge, which is worse than showing nothing.
 */
function headerOf(src, label) {
	const start = src.indexOf('v-if="createOpen"');
	expect(start, `${label}: no editor block`).toBeGreaterThan(-1);
	const end = src.indexOf("card-body", start);
	return src.slice(start, end);
}

describe.each(Object.entries(SCREENS))("%s — the editor states what it is editing", (label, src) => {
	it("shows the source voucher's docstatus in the editor header", () => {
		const header = headerOf(src, label);
		expect(header).toMatch(/<StatusBadge/);
		expect(header).toMatch(/:docstatus="editingDocstatus"/);
	});

	// The invariant that keeps the badge truthful.
	it("clears the status everywhere it clears the name", () => {
		const names = (src.match(/editingName\.value = ""/g) || []).length;
		const statuses = (src.match(/editingDocstatus\.value = null/g) || []).length;
		expect(names, `${label}: editingName is never cleared at all`).toBeGreaterThan(0);
		expect(statuses).toBe(names);
	});

	it("captures the status wherever it captures the name", () => {
		expect(src).toMatch(/editingName\.value = detail\.value\.name;/);
		expect(src).toMatch(/editingDocstatus\.value = detail\.value\.docstatus;/);
	});

	// "Amend" is the word for cancelling a posted voucher. A draft edit deletes
	// and re-creates, which is not the same promise.
	it("does not call a draft edit an amendment", () => {
		const start = src.indexOf("const formTitle");
		expect(start, `${label}: no formTitle`).toBeGreaterThan(-1);
		const title = src.slice(start, src.indexOf(");", start));
		expect(title, `${label}: formTitle never looks at docstatus`).toMatch(/editingDocstatus/);
	});
});
