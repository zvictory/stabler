import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const deal360Path = resolve(here, "../pages/crm/Deal360View.vue");
const cockpitPath = resolve(here, "../pages/crm/ManagerCockpit.vue");

const deal360Src = readFileSync(deal360Path, "utf8");
const cockpitSrc = readFileSync(cockpitPath, "utf8");

describe("CRM 360 & Manager Cockpit Contract Tests", () => {
	it("does not contain Desk links in Deal 360 or Manager Cockpit", () => {
		expect(deal360Src).not.toContain("/app/");
		expect(deal360Src).not.toContain("/desk/");
		expect(cockpitSrc).not.toContain("/app/");
		expect(cockpitSrc).not.toContain("/desk/");
	});

	it("uses MoneyInput for monetary values", () => {
		expect(deal360Src).toContain("MoneyInput");
		expect(cockpitSrc).toContain("MoneyInput");
	});

	it("uses DateInput for date inputs", () => {
		expect(deal360Src).toContain("DateInput");
	});

	it("renders EmptyState components when data is absent", () => {
		expect(deal360Src).toContain("EmptyState");
		expect(cockpitSrc).toContain("EmptyState");
	});
});
