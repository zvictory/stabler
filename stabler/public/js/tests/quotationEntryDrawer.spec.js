import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const drawerPath = resolve(here, "../components/QuotationEntryDrawer.vue");
const drawerSrc = readFileSync(drawerPath, "utf8");

describe("QuotationEntryDrawer Vue Contract Tests", () => {
	it("does not contain any Frappe Desk /app/ or /desk/ links", () => {
		expect(drawerSrc).not.toContain("/app/");
		expect(drawerSrc).not.toContain("/desk/");
	});

	it("uses MoneyInput and DateInput", () => {
		expect(drawerSrc).toContain("MoneyInput");
		expect(drawerSrc).toContain("DateInput");
		expect(drawerSrc).not.toContain('type="number"');
		expect(drawerSrc).not.toContain('type="date"');
	});

	it("accepts rfq prop and calls get_quotation_defaults", () => {
		expect(drawerSrc).toContain("rfq:");
		expect(drawerSrc).toContain("stabler.api.sourcing.get_quotation_defaults");
	});

	it("passes rfq parameter to save_supplier_quotation", () => {
		expect(drawerSrc).toContain("stabler.api.sourcing.save_supplier_quotation");
		expect(drawerSrc).toContain("rfq:");
	});
});
