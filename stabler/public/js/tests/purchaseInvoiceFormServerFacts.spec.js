import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { grossRate } from "../composables/pricing.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/purchasing/PurchaseInvoiceForm.vue"), "utf8");

/**
 * Same defect class as purchaseOrderFormServerFacts.spec.js, one screen over.
 * `useDocumentForm.load()` replaces the model with `fromDetail(detail)` and nothing
 * else (useDocumentForm.js:71-73), so a key `fromDetail` leaves out does not exist
 * on `form`. The invoice view reads these straight off the model:
 *
 *   - `canPay` — `form.value.docstatus === 1 && PAYABLE_STATUSES.has(form.value.status)`;
 *     `canReturn` — `form.value.docstatus === 1` (PurchaseInvoiceForm.vue `canPay`, `canReturn`);
 *   - `<PaymentModal :invoice-name="form?.name" :modified="form?.modified">` — the
 *     payment is recorded against this name and guarded by this timestamp;
 *   - `submitReturn` posts `purchase_invoice: form.value.name`; the print link is
 *     `'/purchasing/invoices/' + form.name + '/print'`.
 *
 * Measured 2026-09-05 on the local site: the submitted, Unpaid ACC-PINV-2026-00883
 * offered only Back and Cancel — no "Make payment", no debit note — although
 * `purchase_invoice_detail` had sent `docstatus`, `status`, `name` and `modified`.
 *
 * Executed, not grepped — a `toContain("docstatus")` would pass on a key spelled
 * right and wired wrong.
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

// fromDetail closes over the imported `grossRate` and the module-level `today`.
function buildFromDetail() {
	const factory = new Function("grossRate", "today", `${extractFunction("fromDetail")}\nreturn fromDetail;`);
	return factory(grossRate, "2026-09-05");
}

// The shape `purchase_invoice_detail` returns for a submitted, unpaid bill.
const unpaidDetail = () => ({
	name: "ACC-PINV-2026-00883",
	modified: "2026-09-05 18:02:11.123456",
	docstatus: 1,
	status: "Unpaid",
	supplier: "SUP-0001",
	supplier_name: "Supplier",
	posting_date: "2026-09-05",
	due_date: "2026-09-05",
	currency: "UZS",
	base_currency: "UZS",
	conversion_rate: 1,
	net_total: 214_800_000,
	total_taxes_and_charges: 0,
	grand_total: 214_800_000,
	base_grand_total: 214_800_000,
	outstanding_amount: 214_800_000,
	is_return: 0,
	debit_notes: [],
	items: [{ item_code: "ITEM-1", item_name: "Item 1", uom: "Nos", qty: 120, rate: 1_790_000, price_list_rate: 0, amount: 214_800_000 }],
});

describe("PurchaseInvoiceForm.fromDetail keeps the server facts the view reads off the model", () => {
	it("carries docstatus and status — the Make payment and debit note gates compare them", () => {
		const model = buildFromDetail()(unpaidDetail());
		expect(model).toMatchObject({ docstatus: 1, status: "Unpaid" });
	});

	it("carries name and modified — the payment modal records against them, the return and print link need the name", () => {
		const model = buildFromDetail()(unpaidDetail());
		expect(model).toMatchObject({ name: "ACC-PINV-2026-00883", modified: "2026-09-05 18:02:11.123456" });
	});

	it("keeps a draft's docstatus 0 as a number the gates can compare", () => {
		const model = buildFromDetail()({ ...unpaidDetail(), docstatus: 0, status: "Draft" });
		expect(model.docstatus).toBe(0);
		expect(model.status).toBe("Draft");
	});
});
