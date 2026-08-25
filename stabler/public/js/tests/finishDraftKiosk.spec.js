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
 * The unconfirmed finish, as the operator meets it.
 *
 * Every assertion here is about one number: zero. A shift that produced nothing
 * good and rejected forty is a real shift, it is the one a manager most wants
 * reported, and it is the one every "is this empty?" shortcut throws away. `||`
 * instead of `??` when prefilling silently replaces it with the remaining
 * quantity; a `:disabled="!producedQty"` on the save button refuses to store it
 * at all. Both look like ordinary defensive code and both mean somebody walks
 * the pallet twice.
 */

function attrOfButton(clickHandler, attr) {
	const click = src.indexOf(`@click="${clickHandler}"`);
	expect(click, `no button bound to ${clickHandler}`).toBeGreaterThan(-1);
	// The attribute belongs to the same tag, i.e. after the previous "<button".
	const tagStart = src.lastIndexOf("<button", click);
	const tag = src.slice(tagStart, click);
	const marker = `${attr}="`;
	const at = tag.indexOf(marker);
	if (at === -1) return null;
	const from = at + marker.length;
	return tag.slice(from, tag.indexOf('"', from));
}

describe("save draft button", () => {
	it("exists", () => {
		expect(src).toContain('@click="saveDraft"');
	});

	it("is not gated on a positive produced quantity", () => {
		// `confirmFinish` is, and should be — posting a Manufacture entry for zero is
		// not a thing. Parking the count is the opposite: it is how the zero gets
		// recorded at all.
		const disabled = attrOfButton("saveDraft", ":disabled") || "";
		expect(disabled).not.toMatch(/producedQty/);
	});

	it("posts to the draft endpoint, not to the stock one", () => {
		const body = src.slice(src.indexOf("async function saveDraft"), src.indexOf("async function discardDraft"));
		expect(body).toContain("manufacturing.save_finish_draft");
		expect(body).not.toContain("make_work_order_stock_entry");
	});
});

describe("confirming a finish", () => {
	it("still refuses a zero quantity", () => {
		// The guard that must NOT be relaxed by any of this: a draft records a zero,
		// a Manufacture entry cannot post one.
		const disabled = attrOfButton("confirmFinish", ":disabled") || "";
		expect(disabled).toMatch(/producedQty/);
	});
});

describe("reopening an order with a parked count", () => {
	const openFinish = src.slice(src.indexOf("async function openFinish"), src.indexOf("async function saveDraft"));

	it("prefills from the draft with ?? so a stored zero survives", () => {
		// `d.produced_qty || producedQty.value` would quietly restore the remaining
		// quantity over a legitimate zero, and the operator confirms a count they
		// did not type.
		expect(openFinish).toMatch(/produced_qty \?\?/);
		expect(openFinish).not.toMatch(/produced_qty \|\|/);
	});

	it("applies the draft after the server's batch suggestion, not before", () => {
		// Otherwise suggest_wo_batch overwrites the operator's own batch number with
		// a generated one — the suggestion is a guess, the draft is what somebody
		// actually entered.
		expect(openFinish.indexOf("suggest_wo_batch")).toBeLessThan(
			openFinish.indexOf("row.finish_draft")
		);
	});

	it("offers a way out of a wrong draft", () => {
		// Without discard, the only exit from a mistyped count is posting it.
		expect(src).toContain('@click="discardDraft"');
	});
});

describe("the board", () => {
	it("shows who parked the count and when", () => {
		// One order, two operators: the person reading the banner is deciding whether
		// to confirm somebody else's count or walk the pallet again.
		expect(src).toContain("r.finish_draft.saved_by");
		expect(src).toContain("r.finish_draft.saved_at");
	});
});
