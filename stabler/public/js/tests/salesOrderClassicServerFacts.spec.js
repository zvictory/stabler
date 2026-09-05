import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { grossRate } from "../composables/pricing.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/sales/SalesOrderFormClassic.vue"), "utf8");

/**
 * Same defect class as purchaseOrderFormServerFacts.spec.js and
 * purchaseInvoiceFormServerFacts.spec.js. `useDocumentForm.load()` replaces the model
 * with `fromDetail(detail)` and nothing else (useDocumentForm.js:71-73), so a key
 * `fromDetail` leaves out does not exist on `form` at all. The view reads these
 * straight off the model (not off the composable's own `docstatus`/`status` refs,
 * which are populated independently from `detail.docstatus`/`detail.status` in
 * `load()` and were never broken):
 *
 *   - `canCloseSo` / `whyStillOpen` — `form.value.status`, `form.value.sales_invoices`,
 *     `form.value.billing_status`, `form.value.per_billed`
 *     (SalesOrderFormClassic.vue `canCloseSo`, `whyStillOpen`);
 *   - `canCreateInvoice` — `form.value?.per_billed`;
 *   - the read-only KPI datagrid — `net_total`, `grand_total`, `advance_paid`,
 *     `per_delivered`, `per_billed` (SalesOrderFormClassic.vue:1065-1086);
 *   - the reservation badge and "Linked invoices" banner —
 *     `form.has_reservations`, `form.sales_invoices` (:885, :913-917);
 *   - the Fulfilment & Billing card (submitted view) — the same totals/progress
 *     plus a per-line table keyed on `it.name` and reading `it.billed_amt`
 *     (:1221-1310).
 *
 * Measured 2026-09-05 (UAT G.3b) on the local site: the Closed, 100%-delivered,
 * 100%-billed SAL-ORD-2026-05895 showed 0 / 0% on every KPI, no reservation badge,
 * no "Linked invoices" banner — although `sales_order_detail` (stabler/api/sales.py)
 * sends all of it.
 *
 * `docstatus`, `name` and `modified` are deliberately NOT covered here: this page
 * never reads `form.value.docstatus`, `form.value.name` or `form.value.modified` —
 * `docstatus`/`status`/`modified` come from useDocumentForm's own refs (set directly
 * from `detail.*` in `load()`, useDocumentForm.js:76-78) and `name` comes from the
 * route (`docName`, SalesOrderFormClassic.vue:359). Adding them to `fromDetail` would
 * be unread, speculative cruft.
 *
 * Executed, not grepped — same shape as the PO/PI specs: a `toContain("per_billed")`
 * would pass on a key spelled right and wired wrong.
 */
function braceMatched(from) {
	let depth = 0;
	for (let i = from; i < src.length; i++) {
		if (src[i] === "{") depth++;
		else if (src[i] === "}" && --depth === 0) return src.slice(from, i + 1);
	}
	throw new Error("unterminated block");
}

function extractFunction(name) {
	const at = src.indexOf(`function ${name}(`);
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	const braceStart = src.indexOf("{", at);
	return src.slice(at, braceStart) + braceMatched(braceStart);
}

// fromDetail closes over the imported `grossRate`; hand it the real one.
function buildFromDetail() {
	const factory = new Function("grossRate", `${extractFunction("fromDetail")}\nreturn fromDetail;`);
	return factory(grossRate);
}

// The shape `sales_order_detail` returns for a submitted, closed, fully-delivered
// and fully-billed order (stabler/api/sales.py sales_order_detail).
const closedDetail = () => ({
	name: "SAL-ORD-2026-05895",
	modified: "2026-09-05 12:00:00.000000",
	transaction_date: "2026-09-01",
	delivery_date: "2026-09-03",
	customer: "CUST-0001",
	customer_name: "Customer",
	company: "Mikas",
	set_warehouse: "Tayyor Mahsulot - M",
	currency: "UZS",
	selling_price_list: "Standard Selling",
	custom_agreement: "",
	conversion_rate: 1,
	net_total: 100_000_000,
	grand_total: 100_000_000,
	advance_paid: 0,
	per_delivered: 100,
	per_billed: 100,
	billing_status: "Fully Billed",
	delivery_status: "Fully Delivered",
	status: "Closed",
	docstatus: 1,
	remarks: "",
	has_reservations: true,
	sales_invoices: [
		{
			name: "ACC-SINV-2026-00042",
			docstatus: 1,
			status: "Paid",
			outstanding_amount: 0,
			grand_total: 100_000_000,
			update_stock: 1,
			posting_date: "2026-09-02",
		},
	],
	items: [
		{
			name: "so-row-1",
			item_code: "ITEM-1",
			item_name: "Item 1",
			uom: "Nos",
			qty: 10,
			delivered_qty: 10,
			billed_amt: 100_000_000,
			reserved_qty: 0,
			rate: 10_000_000,
			price_list_rate: 0,
			amount: 100_000_000,
		},
	],
});

describe("SalesOrderFormClassic.fromDetail keeps the server facts the view reads off the model", () => {
	it("keeps status — canCloseSo and whyStillOpen compare form.value.status, not just the composable's own ref", () => {
		const model = buildFromDetail()(closedDetail());
		expect(model.status).toBe("Closed");
	});

	it("keeps net_total and grand_total — the read-only KPI datagrid formats them", () => {
		const model = buildFromDetail()(closedDetail());
		expect(model).toMatchObject({ net_total: 100_000_000, grand_total: 100_000_000 });
	});

	it("keeps per_delivered and per_billed — the KPI strip and the Fulfilment & Billing progress bars read them", () => {
		const model = buildFromDetail()(closedDetail());
		expect(model).toMatchObject({ per_delivered: 100, per_billed: 100 });
	});

	it("keeps advance_paid and billing_status — the Fulfilment card and whyStillOpen's explanation read them", () => {
		const model = buildFromDetail()(closedDetail());
		expect(model).toMatchObject({ advance_paid: 0, billing_status: "Fully Billed" });
	});

	it("keeps has_reservations and sales_invoices — the reservation badge and the Linked invoices banner read them", () => {
		const detail = closedDetail();
		const model = buildFromDetail()(detail);
		expect(model.has_reservations).toBe(true);
		expect(model.sales_invoices).toEqual(detail.sales_invoices);
	});

	it("keeps each line's row name and billed amount — the fulfilment table keys on name and reads billed_amt", () => {
		const model = buildFromDetail()(closedDetail());
		expect(model.items[0]).toMatchObject({ name: "so-row-1", billed_amt: 100_000_000 });
	});
});
