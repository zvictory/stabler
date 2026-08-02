import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const routerPath = resolve(here, "../router.js");
const deal360Path = resolve(here, "../pages/crm/Deal360View.vue");
const cockpitPath = resolve(here, "../pages/crm/ManagerCockpit.vue");
const crmHomePath = resolve(here, "../pages/crm/CrmHome.vue");

const routerSrc = readFileSync(routerPath, "utf8");
const deal360Src = readFileSync(deal360Path, "utf8");
const cockpitSrc = readFileSync(cockpitPath, "utf8");
const crmHomeSrc = readFileSync(crmHomePath, "utf8");

describe("CRM 360 & Manager Cockpit Router Reachability & Contract Tests", () => {
	it("verifies router imports and registers Deal 360 & Manager Cockpit routes", () => {
		// Import statements
		expect(routerSrc).toContain('import Deal360View from "./pages/crm/Deal360View.vue";');
		expect(routerSrc).toContain('import ManagerCockpit from "./pages/crm/ManagerCockpit.vue";');

		// Deal 360 child route registration under /crm
		expect(routerSrc).toContain('path: "deals/:name"');
		expect(routerSrc).toContain('name: "crm-deal-360"');
		expect(routerSrc).toContain("component: Deal360View");

		// Manager Cockpit child route registration under /crm
		expect(routerSrc).toContain('path: "cockpit"');
		expect(routerSrc).toContain('name: "crm-cockpit"');
		expect(routerSrc).toContain("component: ManagerCockpit");
	});

	it("verifies CrmHome navigation tab gating for Manager Cockpit", () => {
		expect(crmHomeSrc).toContain('name: "crm-cockpit"');
		expect(crmHomeSrc).toContain('path: "/crm/cockpit"');
		expect(crmHomeSrc).toContain("isManager");
	});

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
