import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/inventory/PriceLists.vue"), "utf8");

/**
 * The bulk grid applies what it can and skips the rest — right for a
 * two-hundred-row screen, where one typo should not discard the other
 * hundred-and-ninety-nine edits. The reporting was the problem:
 *
 *   saveSuccess = t("{0} price(s) updated successfully.", [res.updated_count || priceUpdates.length])
 *
 * `0 || 1` is 1, so a batch where the server saved NOTHING announced the number
 * of lines sent as the number saved. It is reachable by typing: the grid's
 * MoneyInput is used with no `min` and `parseMoneyInput("-5")` returns -5
 * (measured 2026-08-27), the endpoint drops negatives, and the grid then
 * reloads — so the old price reappears under a success message and reads as
 * "saved, and that is what it saved".
 *
 * node environment, no jsdom: `saveChanges` is extracted and run against stubs,
 * as in stockReconciliationReceipt.spec.js.
 */
function saveChangesSource() {
	const start = src.indexOf("async function saveChanges()");
	expect(start, "no saveChanges in the SFC").toBeGreaterThan(-1);
	const end = src.indexOf("\n}", start);
	expect(end, "unterminated saveChanges").toBeGreaterThan(start);
	return src.slice(start, end + 2);
}

const DEPS = [
	"hasChanges",
	"selectedPriceList",
	"saving",
	"error",
	"saveSuccess",
	"dirtyMap",
	"activePlCurrency",
	"call",
	"t",
	"loadMatrix",
];

async function save({ dirty, serverResponse }) {
	const stubs = {
		hasChanges: { value: Object.keys(dirty).length > 0 },
		selectedPriceList: { value: "Standard Selling" },
		saving: { value: false },
		error: { value: "" },
		saveSuccess: { value: "" },
		dirtyMap: { value: { ...dirty } },
		activePlCurrency: { value: "UZS" },
		call: async () => serverResponse,
		t: (s, args) => (args ? String(s).replace("{0}", args[0]) : s),
		loadMatrix: async () => {},
	};
	const build = new Function(...DEPS, `${saveChangesSource()}\nreturn saveChanges;`);
	await build(...DEPS.map((d) => stubs[d]))();
	return stubs;
}

describe("what the bulk price grid reports after a save", () => {
	it("does not claim a saved count the server never returned", async () => {
		const { saveSuccess, error } = await save({
			dirty: { "ITEM-A": -5 },
			serverResponse: { status: "ok", updated_count: 0, rejected: ["ITEM-A"] },
		});
		expect(saveSuccess.value, "nothing was saved, so nothing should be announced as saved").not.toMatch(/1/);
		expect(error.value, "the refused line must be named").toContain("ITEM-A");
	});

	it("names every refused line while confirming the ones that landed", async () => {
		const { saveSuccess, error } = await save({
			dirty: { "ITEM-A": 120, "ITEM-B": -5, "ITEM-C": -2 },
			serverResponse: { status: "ok", updated_count: 1, rejected: ["ITEM-B", "ITEM-C"] },
		});
		expect(saveSuccess.value).toContain("1");
		expect(error.value).toContain("ITEM-B");
		expect(error.value).toContain("ITEM-C");
	});

	it("says nothing about refusals on an ordinary save", async () => {
		const { saveSuccess, error } = await save({
			dirty: { "ITEM-A": 120, "ITEM-B": 130 },
			serverResponse: { status: "ok", updated_count: 2, rejected: [] },
		});
		expect(saveSuccess.value).toContain("2");
		expect(error.value).toBe("");
	});

	it("still confirms the save when an older worker sends no rejected list", async () => {
		const { saveSuccess, error } = await save({
			dirty: { "ITEM-A": 120 },
			serverResponse: { status: "ok", updated_count: 1 },
		});
		expect(saveSuccess.value).toContain("1");
		expect(error.value).toBe("");
	});
});
