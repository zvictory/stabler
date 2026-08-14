import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const workspacePath = resolve(here, "../pages/tender/SourcingWorkspace.vue");
const workspaceSrc = readFileSync(workspacePath, "utf8");

describe("SourcingWorkspace Vue Contract Tests", () => {
	it("does not contain any Frappe Desk /app/ or /desk/ links", () => {
		expect(workspaceSrc).not.toContain("/app/");
		expect(workspaceSrc).not.toContain("/desk/");
	});

	it("does not use raw number or date inputs", () => {
		expect(workspaceSrc).not.toContain('type="number"');
		expect(workspaceSrc).not.toContain('type="date"');
	});

	it("renders EmptyState when no deal is selected", () => {
		expect(workspaceSrc).toContain("EmptyState");
	});

	it("links to RFQ creation and detail pages", () => {
		expect(workspaceSrc).toContain("tender-rfq-new");
		expect(workspaceSrc).toContain("tender-rfq-detail");
	});

	it("keeps save decision and approve decision actions separate", () => {
		expect(workspaceSrc).toContain("save_sourcing_decision");
		expect(workspaceSrc).toContain("approve_sourcing_decision");
	});
});
