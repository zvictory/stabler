import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { grossRate } from "../composables/pricing.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/purchasing/PurchaseOrderForm.vue"), "utf8");

/**
 * `useDocumentForm.load()` replaces the model with `fromDetail(detail)` and nothing
 * else (useDocumentForm.js:71-73), so whatever `fromDetail` leaves out does not exist
 * on `form` at all. The view reads these straight off the model:
 *
 *   - `canReceive` / `canCreateInvoice` — `form.value.docstatus === 1`, `per_received`,
 *     `purchase_invoices` (PurchaseOrderForm.vue `canReceive`, `canCreateInvoice`);
 *   - the read-only KPI strip — `net_total`, `grand_total`, `per_received`, `per_billed`;
 *   - the receipts banner — `purchase_receipts`;
 *   - `openReceive` — each line's `name` (the `po_detail` the server insists on:
 *     purchasing.py `create_purchase_receipt_from_po`, "po_detail is required") and
 *     `received_qty` (pending = qty − received; also the per-line badge).
 *
 * Measured 2026-09-05 in the RU walk on a submitted Mikas order (screen 14c): no
 * Receive, no Create Invoice, every KPI "—". `purchase_order_detail` had sent all of
 * it; `fromDetail` dropped it on the floor.
 *
 * Executed, not grepped — same shape as purchaseOrderTenderDeal.spec.js: a
 * `toContain("docstatus")` would pass on a key spelled right and wired wrong.
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

// The shape `purchase_order_detail` returns for a submitted, partly received order.
const submittedDetail = () => ({
	name: "PUR-ORD-2026-00009",
	docstatus: 1,
	status: "To Receive and Bill",
	supplier: "SUP-0001",
	supplier_name: "Supplier",
	currency: "UZS",
	base_currency: "UZS",
	conversion_rate: 1,
	transaction_date: "2026-09-05",
	schedule_date: "2026-09-05",
	net_total: 214_800_000,
	grand_total: 214_800_000,
	per_received: 16.67,
	per_billed: 0,
	purchase_invoices: [{ name: "ACC-PINV-2026-00883", docstatus: 1 }],
	purchase_receipts: [{ name: "MAT-PRE-2026-00012", docstatus: 1 }],
	items: [
		{
			name: "po-row-1",
			item_code: "ITEM-1",
			item_name: "Item 1",
			uom: "Nos",
			qty: 120,
			received_qty: 20,
			rate: 1_790_000,
			price_list_rate: 0,
			amount: 214_800_000,
		},
	],
});

describe("PurchaseOrderForm.fromDetail keeps the server facts the view reads off the model", () => {
	it("carries docstatus, status, progress and totals for the action gates and the KPI strip", () => {
		const model = buildFromDetail()(submittedDetail());
		expect(model).toMatchObject({
			docstatus: 1,
			status: "To Receive and Bill",
			net_total: 214_800_000,
			grand_total: 214_800_000,
			per_received: 16.67,
			per_billed: 0,
		});
	});

	it("carries the linked invoices and receipts the Create Invoice gate and the banner read", () => {
		const detail = submittedDetail();
		const model = buildFromDetail()(detail);
		expect(model.purchase_invoices).toEqual(detail.purchase_invoices);
		expect(model.purchase_receipts).toEqual(detail.purchase_receipts);
	});

	it("keeps each line's row name and received qty — the receive dialog posts po_detail and pending = qty − received", () => {
		const model = buildFromDetail()(submittedDetail());
		expect(model.items[0]).toMatchObject({ name: "po-row-1", received_qty: 20 });
	});

	it("does not invent progress on a draft: docstatus 0 stays a number the gates can compare", () => {
		const model = buildFromDetail()({ ...submittedDetail(), docstatus: 0, status: "Draft", per_received: 0 });
		expect(model.docstatus).toBe(0);
		expect(model.per_received).toBe(0);
	});
});
