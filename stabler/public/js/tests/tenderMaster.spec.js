import { describe, expect, it } from "vitest";

import {
	LANES,
	createLatestRequestGuard,
	groupTenderMasters,
	normalizeTenderMaster,
	tenderMasterListParams,
} from "../composables/tenderMaster.js";

describe("Tender Master projections", () => {
	it("groups records by the backend-derived lane, never by the typed status", () => {
		// TND-3 carries a typed status of "Submitted" and no derived lane: the
		// board must NOT promote it on the strength of a hand-typed field, or the
		// lane stops being a projection of the lots and starts drifting again.
		const grouped = groupTenderMasters([
			{ name: "TND-1", stage: "Active", status: "New" },
			{ name: "TND-2", stage: "Awaiting Result", status: "Won" },
			{ name: "TND-3", status: "Submitted" },
		]);

		expect(grouped.map((lane) => lane.key)).toEqual(LANES);
		expect(grouped.flatMap((lane) => lane.records).map((row) => row.name)).toEqual([
			"TND-3",
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

	it("shows the derived total, not the typed one, when permissions hide every lot", () => {
		// `lot_count` counts only the lots the caller may read, so 0 does not mean
		// "this tender has no lots" — it also means "you may see none of them". The
		// detail summary always reports the derived total, so any fallback to the
		// parent's typed `estimated_total` makes the card and the drill-down state
		// different figures for the same record, which is the drift the derived
		// board exists to remove.
		expect(
			normalizeTenderMaster({
				lot_count: 0,
				lot_estimated_total: 0,
				estimated_total: 1000000,
			})
		).toMatchObject({ lotCount: 0, estimatedTotal: 0 });
	});

	it("surfaces the lot breakdown the card reconciles against its drill-down", () => {
		expect(
			normalizeTenderMaster({
				lot_count: 5,
				open_lot_count: 3,
				submitted_lot_count: 1,
				won_lot_count: 2,
				lost_lot_count: 0,
				policy_gap_count: 4,
				risk_count: 1,
				earliest_deadline: "2026-08-01",
			})
		).toMatchObject({
			lotCount: 5,
			openLotCount: 3,
			submittedLotCount: 1,
			wonLotCount: 2,
			lostLotCount: 0,
			policyGapCount: 4,
			riskCount: 1,
			earliestDeadline: "2026-08-01",
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
