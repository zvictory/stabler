import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/SourcingWorkspace.vue"), "utf8");

/**
 * The sourcing header's "Add quotation" button is bound as `@click="openAddQuotation"`,
 * so Vue hands the handler the native MouseEvent as its first argument. The handler
 * took that as the RFQ to pre-select (`rfq || ""` keeps any truthy object), the
 * QuotationEntryDrawer received a MouseEvent for `:rfq`, and the server answered
 * 404 "RFQ not found: {isTrusted…}" (sourcing.py). Measured 2026-09-05 in the RU
 * walk, step B4; the workaround was to add quotations from an RFQ's own page.
 *
 * Only the `?rfq=` deep link (SourcingWorkspace.vue, onMounted) passes a real name.
 * The handler is the one place that knows what an RFQ name looks like, so it decides:
 * a string is a name, anything else means "no pre-selection".
 *
 * Executed, not grepped — same shape as purchaseOrderTenderDeal.spec.js.
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

// openAddQuotation closes over three refs; stand them in as plain { value } boxes.
function build(refs) {
	const factory = new Function(
		"entryQuotationName",
		"entryRfq",
		"entryOpen",
		`${extractFunction("openAddQuotation")}\nreturn openAddQuotation;`
	);
	return factory(refs.entryQuotationName, refs.entryRfq, refs.entryOpen);
}

const staleRefs = () => ({
	entryQuotationName: { value: "PUR-SQTN-2026-00047" },
	entryRfq: { value: "PUR-RFQ-2026-00001" },
	entryOpen: { value: false },
});

describe("SourcingWorkspace.openAddQuotation as the header button's bare click handler", () => {
	it("opens a blank entry: the MouseEvent Vue passes is not an RFQ name", () => {
		const refs = staleRefs();
		build(refs)({ isTrusted: true, type: "click", target: {} });
		expect(refs.entryRfq.value).toBe("");
		expect(refs.entryQuotationName.value).toBe("");
		expect(refs.entryOpen.value).toBe(true);
	});

	it("still pre-selects the RFQ when the ?rfq= deep link hands it a name", () => {
		const refs = staleRefs();
		build(refs)("PUR-RFQ-2026-00003");
		expect(refs.entryRfq.value).toBe("PUR-RFQ-2026-00003");
		expect(refs.entryOpen.value).toBe(true);
	});
});
