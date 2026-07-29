import { describe, expect, it } from "vitest";

import {
	createLatestRequestGuard,
	groupTenderMasters,
	normalizeTenderMaster,
	tenderMasterListParams,
} from "../composables/tenderMaster.js";

describe("Tender Master projections", () => {
	it("groups records by approved CRM stage order without duplicating them", () => {
		const grouped = groupTenderMasters([
			{ name: "TND-1", status: "Sourcing" },
			{ name: "TND-2", status: "Submitted" },
		]);

		expect(grouped.map((lane) => lane.key)).toEqual([
			"New",
			"Sourcing",
			"Bid Preparation",
			"Submitted",
			"Closed",
		]);
		expect(grouped.flatMap((lane) => lane.records).map((row) => row.name)).toEqual([
			"TND-1",
			"TND-2",
		]);
	});

	it("preserves zero values instead of replacing them with placeholders", () => {
		expect(normalizeTenderMaster({ lot_count: 0, estimated_total: 0 })).toMatchObject({
			lotCount: 0,
			estimatedTotal: 0,
		});
	});
});

describe("latest Tender Master requests", () => {
	it("rejects an earlier request after company changes away and back", () => {
		const guard = createLatestRequestGuard();
		const firstCompanyARequest = guard.start();
		guard.start();
		const secondCompanyARequest = guard.start();

		expect(guard.isLatest(firstCompanyARequest)).toBe(false);
		expect(guard.isLatest(secondCompanyARequest)).toBe(true);
	});
});

describe("Tender Master list query mapping", () => {
	it("forwards only supported CRM filters from a route query", () => {
		expect(
			tenderMasterListParams({
				status: "won",
				stage: "submitted",
				risk: "risk",
				deal: "LOT-001",
				from_date: "2026-07-01",
				to_date: "2026-07-31",
				days: "90",
				tab: "overview",
			})
		).toEqual({
			status: "won",
			stage: "submitted",
			risk: "risk",
			deal: "LOT-001",
			from_date: "2026-07-01",
			to_date: "2026-07-31",
		});
	});
});
