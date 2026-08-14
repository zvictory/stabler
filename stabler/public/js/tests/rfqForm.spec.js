import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const formPath = resolve(here, "../pages/tender/rfq/RfqForm.vue");
const formSrc = readFileSync(formPath, "utf8");

describe("RfqForm Vue Contract Tests", () => {
	it("does not contain any Frappe Desk /app/ or /desk/ links", () => {
		expect(formSrc).not.toContain("/app/");
		expect(formSrc).not.toContain("/desk/");
	});

	it("uses MoneyInput and DateInput", () => {
		expect(formSrc).toContain("MoneyInput");
		expect(formSrc).toContain("DateInput");
		expect(formSrc).not.toContain('type="number"');
		expect(formSrc).not.toContain('type="date"');
	});

	it("pre-fills items using get_deal_rfq_defaults", () => {
		expect(formSrc).toContain("stabler.api.sourcing.get_deal_rfq_defaults");
	});

	it("submits draft RFQ through create_rfq", () => {
		expect(formSrc).toContain("stabler.api.sourcing.create_rfq");
		expect(formSrc).toContain("company: activeCompany.value");
	});
});
