import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(
	resolve(here, "../pages/manufacturing/ManufacturingOperatorBoard.vue"),
	"utf8"
);

/**
 * The button that writes one operator's materials off the Work Order.
 *
 * Its guard is doing more than input validation. Two of the states it refuses are
 * ones where the *backend* would also refuse — deliberately, because a shop-floor
 * tablet should not learn that from a round trip and a red box — and one is a
 * state where nothing refuses at all:
 *
 *   - `!consumeEnabled` is the site without `Manufacturing Settings.
 *     material_consumption`. Measured on genesis-test 2026-08-25: with it off,
 *     ERPNext builds the write-off from the whole BOM instead of from what is
 *     actually left in WIP, so a submitted entry counts material that was already
 *     consumed a second time. Nothing throws.
 *   - `!consumeItems.length` reaches the endpoint as "no subset given", which
 *     ERPNext reads as "consume everything the BOM says" — the other operator's
 *     material included, under this operator's name.
 *   - `consumeLoading` is the gap between opening the dialog for one order and its
 *     list arriving. The refs still hold the previous order's rows.
 *
 * The expression is pulled out of the shipped SFC and executed, not string-matched.
 * A `toContain("consumeEnabled")` assertion passes just as happily on a guard
 * wired backwards. @vue/test-utils is not a devDependency here (same constraint as
 * remittanceMoneyGates.spec.js), so the component is not mounted; the guard is.
 */
function disabledExpression(clickHandler, label) {
	const click = src.indexOf(`@click="${clickHandler}"`);
	expect(click, `${label}: no button bound to ${clickHandler}`).toBeGreaterThan(-1);
	const marker = ':disabled="';
	const start = src.lastIndexOf(marker, click);
	expect(start, `${label}: the ${clickHandler} button carries no :disabled binding`).toBeGreaterThan(-1);
	const bodyStart = start + marker.length;
	const end = src.indexOf('"', bodyStart);
	expect(end, `${label}: unterminated :disabled binding`).toBeGreaterThan(bodyStart);
	return src.slice(bodyStart, end);
}

const EXPR = disabledExpression("confirmConsume", "write-off");

const READY = {
	busy: "",
	consumeTarget: { name: "WO-9" },
	consumeLoading: false,
	consumeEnabled: true,
	consumeItems: [{ item_code: "RAW-MLK", qty: 12 }],
};

function isDisabled(overrides = {}) {
	const scope = { ...READY, ...overrides };
	const fn = new Function(
		"isBusy",
		"consumeTarget",
		"consumeLoading",
		"consumeEnabled",
		"consumeItems",
		`return (${EXPR});`
	);
	return !!fn(
		(name) => scope.busy === name,
		scope.consumeTarget,
		scope.consumeLoading,
		scope.consumeEnabled,
		scope.consumeItems
	);
}

describe("operator write-off button", () => {
	it("is live once the operator has their own list and a quantity on it", () => {
		expect(isDisabled()).toBe(false);
	});

	it("refuses a site where continuous consumption is switched off", () => {
		// ERPNext accepts the entry here and silently double-counts. This button is
		// the only thing between that and an operator's thumb.
		expect(isDisabled({ consumeEnabled: false })).toBe(true);
	});

	it("refuses an empty list", () => {
		// Posted with no items, the endpoint falls through to ERPNext's own BOM
		// expansion — the other operator's material, written off under this name.
		expect(isDisabled({ consumeItems: [] })).toBe(true);
	});

	it("refuses a zero or negative quantity", () => {
		expect(isDisabled({ consumeItems: [{ item_code: "RAW-MLK", qty: 0 }] })).toBe(true);
		expect(isDisabled({ consumeItems: [{ item_code: "RAW-MLK", qty: -1 }] })).toBe(true);
	});

	it("refuses one bad row among good ones", () => {
		expect(
			isDisabled({
				consumeItems: [
					{ item_code: "RAW-MLK", qty: 12 },
					{ item_code: "RAW-SGR", qty: 0 },
				],
			})
		).toBe(true);
	});

	it("refuses while the list is still loading", () => {
		// Otherwise the previous order's rows are still in the refs, and they would
		// be posted against the order now on screen.
		expect(isDisabled({ consumeLoading: true, consumeItems: [] })).toBe(true);
		expect(isDisabled({ consumeLoading: true })).toBe(true);
	});

	it("refuses while a post for this order is already in flight", () => {
		expect(isDisabled({ busy: "WO-9" })).toBe(true);
	});
});
