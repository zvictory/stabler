import { describe, expect, it } from "vitest";
import { reachOf } from "../composables/sourcingReach.js";

const MIN_S = 5;
const MIN_C = 2;

describe("what an unsaved RFQ invitation reaches", () => {
	it("counts vendors, not the rows they appear in", () => {
		const out = reachOf(
			[
				{ supplier: "ACME", country: "Uzbekistan" },
				{ supplier: "ACME", country: "Uzbekistan" },
				{ supplier: "BETA", country: "Turkey" },
			],
			MIN_S,
			MIN_C,
		);
		expect(out.suppliers).toBe(2);
		expect(out.countries).toBe(2);
	});

	it("does not treat a blank country as a country", () => {
		// The Python twin strips before testing; if this half did not, the form
		// would promise two countries and the workspace would report one.
		const out = reachOf(
			[
				{ supplier: "ACME", country: "Uzbekistan" },
				{ supplier: "BETA", country: "  " },
				{ supplier: "GAMMA" },
			],
			MIN_S,
			MIN_C,
		);
		expect(out.countries).toBe(1);
		expect(out.unknown_country).toBe(2);
	});

	it("stops calling a vendor countryless once any row names its country", () => {
		const out = reachOf(
			[
				{ supplier: "ACME", country: "" },
				{ supplier: "ACME", country: "Turkey" },
			],
			MIN_S,
			MIN_C,
		);
		expect(out.unknown_country).toBe(0);
		expect(out.countries).toBe(1);
	});

	it("says one country cannot reach two, however many vendors are picked", () => {
		const invited = Array.from({ length: 9 }, (_, i) => ({
			supplier: `V${i}`,
			country: "Uzbekistan",
		}));
		const out = reachOf(invited, MIN_S, MIN_C);
		expect(out.meets_suppliers).toBe(true);
		expect(out.meets_countries).toBe(false);
	});

	it("reaches nothing when nothing is picked", () => {
		const out = reachOf([], MIN_S, MIN_C);
		expect(out).toEqual({
			suppliers: 0,
			countries: 0,
			unknown_country: 0,
			meets_suppliers: false,
			meets_countries: false,
		});
	});

	it("survives a null list rather than breaking the form", () => {
		expect(reachOf(null, MIN_S, MIN_C).suppliers).toBe(0);
	});

	it("answers in the same shape its Python twin does", () => {
		// The two are read by two badges on two screens describing one vendor
		// set. A key present on one side and absent on the other is how the
		// screens start disagreeing.
		expect(Object.keys(reachOf([{ supplier: "A", country: "UZ" }], 1, 1)).sort()).toEqual([
			"countries",
			"meets_countries",
			"meets_suppliers",
			"suppliers",
			"unknown_country",
		]);
	});
});
