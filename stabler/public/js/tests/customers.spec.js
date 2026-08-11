import { afterEach, describe, expect, it, vi } from "vitest";
import { customerSearcher } from "../composables/customers.js";

afterEach(() => {
	vi.unstubAllGlobals();
});

function stubResponse(payload) {
	const fetch = vi.fn().mockResolvedValue({
		ok: true,
		status: 200,
		json: async () => payload,
	});
	vi.stubGlobal("fetch", fetch);
	return fetch;
}

describe("customerSearcher", () => {
	it("hands the typeahead the rows it got", async () => {
		const fetch = stubResponse({
			message: [
				{ name: "CUST-0001", customer_name: "Abdulla Savdo" },
				{ name: "CUST-0002", customer_name: "Abror LLC" },
			],
		});

		const rows = await customerSearcher("Mikas")("ab");

		expect(rows.map((r) => r.name)).toEqual(["CUST-0001", "CUST-0002"]);
		expect(fetch).toHaveBeenCalledWith(
			"/api/method/stabler.api.sales.list_customers",
			expect.objectContaining({ method: "POST" })
		);
	});

	it("never returns a non-array, whatever the endpoint answers", async () => {
		// The İhale Giriş Merkezi drawer used to call list_customers_with_balances,
		// whose {rows: [...]} envelope is not a list. Typeahead.vue silently turns
		// anything that is not an array into [], so the dropdown stayed empty on
		// every keystroke with no error anywhere. A searcher that can leak a
		// non-array is the bug; this is the guard that makes it impossible.
		stubResponse({ message: { rows: [{ name: "CUST-0001" }], total_count: 1 } });

		expect(await customerSearcher("Mikas")("ab")).toEqual([]);
	});

	it("resolves the company at call time so a company switch is picked up", async () => {
		// The searcher is built once when the form is set up; the active company can
		// change after that. Freezing it would search the previous tenant's customers.
		let company = "Mikas";
		const fetch = stubResponse({ message: [] });
		const search = customerSearcher(() => company);

		await search("ab");
		company = "Anjan";
		await search("ab");

		const sent = fetch.mock.calls.map(([, init]) => new URLSearchParams(init.body).get("company"));
		expect(sent).toEqual(["Mikas", "Anjan"]);
	});

	it("survives a failing request instead of breaking the form", async () => {
		vi.stubGlobal(
			"fetch",
			vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) })
		);

		expect(await customerSearcher("Mikas")("ab")).toEqual([]);
	});
});
