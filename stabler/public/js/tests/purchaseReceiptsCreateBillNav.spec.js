import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/purchasing/PurchaseReceipts.vue"), "utf8");

/**
 * UAT 2026-09-05, step 18c (RU walk): "create invoice from receipt" never opens
 * the new draft. `createBill()` pushed `{ path: "/purchasing/invoices", query:
 * { open: res.name } }` — the invoices list (PurchaseInvoices.vue:26-28) reads
 * only `from_date`/`to_date`/`tender_only` from its query, so `open` was dead
 * and the user landed on the plain list instead of the bill they just created.
 *
 * `purchaseInvoiceFormPath` is the fix: the same `/purchasing/invoices/:name`
 * route PurchaseInvoiceForm.vue itself already pushes to after its own create
 * (PurchaseInvoiceForm.vue:746) and after a debit-note create (:756).
 *
 * Executed, not grepped — asserting the literal query object stayed out of the
 * source would not catch a fix that still built the wrong path string.
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

function buildPurchaseInvoiceFormPath() {
	const factory = new Function(`${extractFunction("purchaseInvoiceFormPath")}\nreturn purchaseInvoiceFormPath;`);
	return factory();
}

describe("PurchaseReceipts.createBill routes straight to the new bill's form", () => {
	it("builds /purchasing/invoices/<name>, the route PurchaseInvoiceForm itself pushes to (UAT 18c)", () => {
		expect(buildPurchaseInvoiceFormPath()("ACC-PINV-2026-00001")).toBe(
			"/purchasing/invoices/ACC-PINV-2026-00001"
		);
	});

	it("never routes through the list's dead ?open= query", () => {
		const path = buildPurchaseInvoiceFormPath()("ACC-PINV-2026-00001");
		expect(path).not.toContain("open");
		expect(path.startsWith("/purchasing/invoices/")).toBe(true);
	});
});
