import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

const workspacePath = resolve(__dirname, "../pages/tender/SourcingWorkspace.vue");
const workspaceSrc = readFileSync(workspacePath, "utf8");

describe("SourcingWorkspace Vue Contract Tests", () => {
	it("does not contain any Frappe Desk /app/ or /desk/ links", () => {
		expect(workspaceSrc).not.toContain("/app/");
		expect(workspaceSrc).not.toContain("/desk/");
	});

	it("uses MoneyInput for numeric amounts and quantities", () => {
		expect(workspaceSrc).toContain("MoneyInput");
	});

	it("uses DateInput for date fields", () => {
		expect(workspaceSrc).toContain("DateInput");
	});

	it("renders EmptyState when no deal is selected or no items exist", () => {
		expect(workspaceSrc).toContain("EmptyState");
	});

	it("calls create_rfq API with deterministic payload shape", () => {
		expect(workspaceSrc).toContain("stabler.api.sourcing.create_rfq");
		expect(workspaceSrc).toContain("item_code");
		expect(workspaceSrc).toContain("qty");
		expect(workspaceSrc).toContain("schedule_date");
	});

	it("preserves draft RFQ semantics without auto email sending", () => {
		expect(workspaceSrc).toContain("Create draft RFQ");
		expect(workspaceSrc).not.toContain("sendmail");
	});
});
