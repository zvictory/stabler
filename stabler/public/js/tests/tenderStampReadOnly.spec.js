// G.18 — the tender/deal a document was booked to was invisible on two
// screens: the Sales Invoice form (no "tender" concept at all) and the
// Expense detail drawer (Journal Entry, via `custom_crm_deal`). The Python
// side is pinned by `stabler.tests.test_related_documents_upstream_links`
// (sales.py's `_deal_display_label`) and `stabler.tests.test_expense_tender_stamp`
// (money.py's `_je_tender_stamp` / `_deal_display_label`) — that is where the
// interesting logic (the organization/lead_name/deal-id fallback chain, the
// legacy-column guard) lives and is executed.
//
// What is left here is wiring, read out of the shipped `.vue` sources rather
// than mounted (no `@vue/test-utils` in this repo — see
// `workOrderLedger.spec.js` for the same house pattern). Wiring is exactly
// where this class of bug lives: `sales_invoice_detail` can return a correct
// `tender_label` and the row still never renders if the template reads the
// wrong flag, or a transform between the API response and the template drops
// the key — precisely how G.17 (elsewhere in this change) turned out to be a
// dropped key, not a missing field.

import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";

const siSrc = readFileSync(
	fileURLToPath(new URL("../pages/sales/SalesInvoiceForm.vue", import.meta.url)),
	"utf8",
);
const expSrc = readFileSync(
	fileURLToPath(new URL("../pages/money/Expenses.vue", import.meta.url)),
	"utf8",
);

/** The header datagrid block — `<div class="datagrid mb-3">` up to its matching close. */
function headerDatagrid(src) {
	const open = src.indexOf('<div class="datagrid mb-3">');
	expect(open, "no header datagrid found").toBeGreaterThan(-1);
	let depth = 0;
	let i = open;
	for (; i < src.length; i++) {
		if (src.startsWith("<div", i)) depth++;
		else if (src.startsWith("</div>", i) && --depth === 0) break;
	}
	return src.slice(open, i);
}

describe("SalesInvoiceForm — the tender it was booked to", () => {
	it("passes the server's detail straight through, unmapped", () => {
		// `sales_invoice_detail` (stabler/api/sales.py) returns `tender` and
		// `tender_label` alongside every other field this form reads. If
		// `fromDetail` ever stopped being the identity function — the exact
		// shape of G.17's root cause on the other three screens this change
		// touches — those two keys could be dropped on the way into `form`
		// while every *other* field on this page kept working, and nothing
		// short of reading this line would notice.
		expect(siSrc).toMatch(/fromDetail:\s*\(d\)\s*=>\s*d,/);
		expect(siSrc).toContain('detailApi: "stabler.api.sales.sales_invoice_detail"');
	});

	it("shows a read-only row only when the invoice actually carries one", () => {
		expect(siSrc).toMatch(/<div v-if="form\.tender" class="datagrid-item">/);
		expect(siSrc).toMatch(/\{\{ t\("Tender"\) \}\}/);
		expect(siSrc).toMatch(/\{\{ form\.tender_label \|\| form\.tender \}\}/);
	});

	it("sits between Customer and Currency in the header datagrid, as designed", () => {
		const block = headerDatagrid(siSrc);
		const order = ['t("Customer")', 'v-if="form.tender"', 't("Currency")'].map((needle) =>
			block.indexOf(needle),
		);
		expect(order.every((i) => i > -1)).toBe(true);
		expect([...order].sort((a, b) => a - b)).toEqual(order);
	});

	it("is display-only — no control a user could edit the stamp through", () => {
		// The brief is explicit: no editing here. A stray `v-model`, `<select>`
		// or `<input>` inside this row would let a user change what the
		// invoice was booked to from a screen that has no save path for it.
		const start = siSrc.indexOf('<div v-if="form.tender" class="datagrid-item">');
		const end = siSrc.indexOf("</div>", siSrc.indexOf("</div>", start) + 1);
		const row = siSrc.slice(start, end);
		expect(row).not.toMatch(/v-model|<select|<input|Typeahead/);
	});
});

describe("Expenses — the tender it was booked to", () => {
	it("loads the drawer straight from the endpoint, unmapped", () => {
		// No `fromDetail`-shaped transform sits between this call and the
		// template on this page — `detail.value` IS the server response, so a
		// key the endpoint adds reaches the template unless the template
		// itself fails to read it (which the next test pins).
		expect(expSrc).toMatch(
			/detail\.value = await call\("stabler\.api\.money\.journal_entry_detail", \{ name \}\);/,
		);
	});

	it("shows a read-only row only when the entry actually carries one", () => {
		expect(expSrc).toMatch(/<div v-if="detail\.tender" class="datagrid-item">/);
		expect(expSrc).toMatch(/\{\{ t\("Tender"\) \}\}/);
		expect(expSrc).toMatch(/\{\{ detail\.tender_label \|\| detail\.tender \}\}/);
	});

	it("sits in the view-mode drawer, after Memo and before Postings", () => {
		// Not the create/edit-mode "Tender (Deal)" picker further down this
		// same file (`form.deal`, a `Typeahead`) — a different field, a
		// different mode, and explicitly out of scope for this change.
		const memo = expSrc.indexOf('t("Memo")');
		const tenderRow = expSrc.indexOf('<div v-if="detail.tender" class="datagrid-item">');
		const postings = expSrc.indexOf('t("Postings")');
		expect([memo, tenderRow, postings].every((i) => i > -1)).toBe(true);
		expect(memo).toBeLessThan(tenderRow);
		expect(tenderRow).toBeLessThan(postings);
	});

	it("is display-only — no control a user could edit the stamp through", () => {
		const start = expSrc.indexOf('<div v-if="detail.tender" class="datagrid-item">');
		const end = expSrc.indexOf("</div>", expSrc.indexOf("</div>", start) + 1);
		const row = expSrc.slice(start, end);
		expect(row).not.toMatch(/v-model|<select|<input|Typeahead/);
	});

	it("is a different field from the edit-mode deal picker, on both label and value", () => {
		// Guards against a future edit "simplifying" this to reuse `form.deal`
		// / "Tender (Deal)" — that field only exists in create/edit mode and
		// would be blank while viewing a submitted entry, silently breaking
		// the read-only row this test pins above.
		expect(expSrc).not.toMatch(/<div v-if="detail\.tender"[\s\S]{0,120}Tender \(Deal\)/);
	});
});
