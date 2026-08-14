import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const detailPath = resolve(here, "../pages/tender/rfq/RfqDetail.vue");
const detailSrc = readFileSync(detailPath, "utf8");

describe("RfqDetail Vue Contract Tests", () => {
	it("does not contain any Frappe Desk /app/ or /desk/ links", () => {
		expect(detailSrc).not.toContain("/app/");
		expect(detailSrc).not.toContain("/desk/");
	});

	it("has record quotation button linking to sourcing workspace with rfq query", () => {
		expect(detailSrc).toContain("Record quotation");
		expect(detailSrc).toContain("recordQuotation");
		expect(detailSrc).toContain("tender-sourcing");
	});
});
