// The recipe is not the operator's to see.
//
// Anjan's ask, 2026-08-31: an operator starts, stops and reports an order and
// nothing else. What goes into the product — which items, in what quantity — is
// the thing they specifically must not learn, because the kiosk is a wall-mounted
// tablet on a shop floor and the bill of materials is the company's own recipe.
//
// This is a leak test, and leak tests are worth writing here because every one of
// the routes below was open on 2026-08-31 and three of the four looked closed:
//
//   list_work_orders     -> 0 rows   (role-scoped; measured empty on anjan)
//   work_order_detail    -> 0 rows   (role-scoped; measured empty on anjan)
//   wo_consumption_preview -> 0 rows (role-scoped; measured empty on anjan)
//   wo_transfer_preview  -> 15 rows WITH QUANTITIES, measured on anjan as
//                           qwerty03@mail.com (Ilyos Nazirov, Manufacturing User
//                           only): R194 27840 Dona, R047 113.806 Dona, ...
//
// The fourth is the one the "Start" button opens. So a test that only checks the
// three scoped endpoints would have passed while the whole bill of materials sat
// on screen — which is exactly what shipped.
//
// Read out of the shipped `.vue` rather than mounted: `@vue/test-utils` is not a
// dependency of this repo and the house pattern is to assert on source.

import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";

const raw = readFileSync(
	fileURLToPath(new URL("../pages/manufacturing/ManufacturingOperatorBoard.vue", import.meta.url)),
	"utf8",
);

// Comments stripped before every search below, and that is not tidiness: this
// file's own subject makes the component's comments full of the words being
// searched for ("required_items", "materials"). Twice already in this repo an
// un-stripped source search matched the prose explaining a rule instead of the
// code obeying it, and passed with the code deleted. Measured, not feared.
const src = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

describe("the kiosk never asks for the bill of materials", () => {
	it("does not call the endpoint that hands out the transfer rows", () => {
		// `wo_transfer_preview` is ERPNext's own material list for this order,
		// item by item with quantities. Measured 2026-08-31 it answers an operator
		// in full. Not calling it is the fix; narrowing the server is the other
		// half, and both are needed — the endpoint stays reachable for managers.
		expect(src).not.toContain("wo_transfer_preview");
	});

	it("does not ask what this operator could write off", () => {
		// `wo_consumption_preview` names items too. Measured across all 8 stabler
		// tenants on 2026-08-31: 0 Material Consumption entries have ever been
		// posted and 0 Items carry an operator role, so the write-off flow this
		// served has never run anywhere. It leaves the kiosk rather than being
		// narrowed, because there is nothing to narrow it for.
		expect(src).not.toContain("wo_consumption_preview");
	});

	it("does not offer to rewrite a planned quantity", () => {
		// `update_work_order_materials` let an operator retype `required_qty` on
		// the card. Seeing the number is the leak; editing it also rewrites the
		// denominator the deviation panel scores people against.
		expect(src).not.toContain("update_work_order_materials");
	});
});

describe("no material reaches the screen", () => {
	it("renders no item row from the order's own material list", () => {
		// The card carried `v-for="it in r.required_items"` with item code, item
		// name and a transferred figure per line.
		expect(src).not.toMatch(/v-for="[^"]*\bin r\.required_items"/);
		expect(src).not.toMatch(/v-model[.\w]*="it\.required_qty"/);
	});

	it("renders no item row in the start dialog", () => {
		// The start dialog was a full editable transfer table — item typeahead,
		// per-row quantity, source-stock figure, BOM-plan variance chip. All of it
		// is the recipe, restated.
		expect(src).not.toMatch(/v-for="\([^)]*\) in transferItems"/);
		expect(src).not.toContain("addTransferItem");
		expect(src).not.toContain("sourceStockLevels");
	});

	it("warns about a sweep without listing what it would sweep", () => {
		// The warning named the other role's unconsumed items — item name and
		// quantity, one line each. The names went because the operator can no
		// longer act on them: with the write-off gone from the kiosk there is no
		// colleague to go and find, only a server that may still refuse.
		expect(src).not.toMatch(/v-for="[^"]*\bin finishSweep"/);
		// The acknowledgement itself survives. `_assert_sweep_is_acknowledged`
		// still refuses a finish server-side, and without a checkbox to answer it
		// the operator would meet a refusal with nothing to do about it.
		expect(src).toContain("acknowledge_sweep");
		expect(src).toContain("sweepBlocked");
	});
});

describe("start still starts the order", () => {
	it("posts the transfer without dictating its contents", () => {
		// The whole point: the button keeps doing what it did — one Material
		// Transfer for Manufacture — but the client no longer says what is in it.
		// `make_work_order_stock_entry` builds the rows from ERPNext when `items`
		// is absent (manufacturing.py:2027, `items: str | None = None`), so this
		// is a subtraction from the request, not a new server path.
		const fn = /async function confirmStart\(\)[\s\S]*?\n}/.exec(src)?.[0] ?? "";
		expect(fn).toContain("Material Transfer for Manufacture");
		expect(fn).not.toMatch(/\bitems:/);
	});

	it("still names the two warehouses, which are places and not materials", () => {
		// A shop-floor operator has to know which store to fetch from and which
		// line it goes to. Neither says what is being fetched.
		const fn = /async function confirmStart\(\)[\s\S]*?\n}/.exec(src)?.[0] ?? "";
		expect(fn).toContain("from_warehouse");
		expect(fn).toContain("to_warehouse");
	});
});
