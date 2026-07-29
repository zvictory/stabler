import { describe, expect, it } from "vitest";

import { groupTenderMasters, normalizeTenderMaster } from "../composables/tenderMaster.js";

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
		expect(grouped.flatMap((lane) => lane.records).map((row) => row.name)).toEqual(["TND-1", "TND-2"]);
	});

	it("preserves zero values instead of replacing them with placeholders", () => {
		expect(normalizeTenderMaster({ lot_count: 0, estimated_total: 0 })).toMatchObject({
			lotCount: 0,
			estimatedTotal: 0,
		});
	});
});
