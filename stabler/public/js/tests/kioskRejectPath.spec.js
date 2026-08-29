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
 * Which of the two reject paths a Finish takes, and why one operator must never
 * be able to take both.
 *
 * The server refuses the combination in both directions:
 *
 *   manufacturing._assert_no_scrap_record            — no Finish-time `scrap_qty`
 *                                                      on an order that has scrap records
 *   Stabler Line Scrap._assert_rejects_were_not_already_reported
 *                                                    — no scrap record on an order
 *                                                      finished with `scrap_qty`
 *
 * and the reason is arithmetic, not policy. `scrap_qty` becomes the Manufacture
 * entry's `process_loss_qty`, which inflates `fg_completed_qty` to good+loss so
 * ERPNext's equality check passes: the raw material for the lost units is drawn
 * and received nowhere, absorbed into the good output's unit cost. A scrap record
 * moves that same material into the scrap warehouse instead. Both, for one order,
 * charges the material twice — and nothing throws, because each number is
 * individually correct.
 *
 * So the exclusivity cannot be left to the server. Reaching it means the operator
 * has already counted the pallet and typed a number, and what they get back is a
 * refusal that reads like a bug. This file pins the decision that keeps them from
 * getting there, EXECUTED end to end: `rejectPath` is pulled out of the shipped
 * SFC, and so is the `scrap_qty` expression the Finish call actually sends, and
 * the second is evaluated against the first. A `toContain` assertion cannot tell
 * a decision that is wired in from one that is merely defined.
 *
 * @vue/test-utils is not a devDependency here — same constraint as
 * finishSweepGuard.spec.js and manufacturingTabGates.spec.js.
 */
function fnSource(name) {
	const start = src.indexOf(`function ${name}(`);
	expect(start, `${name}() is not in the shipped component`).toBeGreaterThan(-1);
	const end = src.indexOf("\n}", start);
	expect(end, `${name}(): unterminated body`).toBeGreaterThan(start);
	return src.slice(start, end + 2);
}

function functionBody(name) {
	return fnSource(name);
}

const rejectPath = new Function(`${fnSource("rejectPath")}\nreturn rejectPath;`)();

/**
 * The `scrap_qty` the Finish call actually carries, taken out of the payload the
 * shipped component builds and evaluated with the real `rejectPath` behind it.
 * This is the assertion that fails if somebody restores the old
 * `Number(scrapQty.value) > 0 ? Number(scrapQty.value) : undefined`.
 */
function sentScrapQty(mode, typedQty, recordedCount) {
	// Scoped to confirmFinish's own body. `make_work_order_stock_entry` is called
	// from three places in this file (start, write-off, finish) and `scrap_qty:`
	// also appears inside rejectPath itself, so anchoring on either alone reads
	// the wrong expression and reports it as a syntax error.
	const body = functionBody("confirmFinish");
	const key = body.indexOf("scrap_qty:");
	expect(key, "the Finish call no longer sends scrap_qty at all").toBeGreaterThan(-1);
	const end = body.indexOf("\n", key);
	const expr = body
		.slice(key + "scrap_qty:".length, end)
		.replace(/,\s*$/, "")
		.trim();
	const fn = new Function(
		"rejectDecision",
		`return (${expr});`
	);
	return fn({ value: rejectPath(mode, typedQty, recordedCount) });
}

describe("an order that already carries a scrap record never sends a second count", () => {
	it("drops the typed number rather than reaching _assert_no_scrap_record", () => {
		// The operator filed the loss with a reason. `scrap_qty` on top of that is
		// the double charge, and the server's refusal would arrive after the
		// pallet was counted.
		expect(rejectPath("count", "7", 1).scrap_qty).toBeUndefined();
	});

	it("sends nothing even through the shipped payload expression", () => {
		expect(sentScrapQty("count", "7", 1)).toBeUndefined();
	});

	it("says so, so the screen can show it instead of offering the box", () => {
		expect(rejectPath("count", "", 1).locked).toBe(true);
	});
});

describe("the reasoned path is the one the kiosk was asked for", () => {
	it("is what an untouched order defaults to", () => {
		// "Киоск 2.0: очередь, крупные кнопки, брак с причиной" — the missing
		// thing was the reason, not the number. The bare count shipped 2026-06-08
		// and was used on 0 of 3757 Manufacture entries.
		expect(rejectPath("reasoned", "", 0).path).toBe("record");
	});

	it("never smuggles the number into the Finish call", () => {
		// The failure this prevents is silent in the other direction: a number
		// typed for the scrap record, sent as `scrap_qty` because the mode was
		// ignored, is a loss recorded twice with nothing refusing it.
		expect(rejectPath("reasoned", "9", 0).scrap_qty).toBeUndefined();
		expect(sentScrapQty("reasoned", "9", 0)).toBeUndefined();
	});

	it("refuses to let Finish run over a number nobody recorded", () => {
		// The other silent failure: reasoned mode with 9 in the box and no record
		// filed. Sending nothing is correct, but dropping the 9 without saying so
		// loses the loss entirely. The Finish button is held instead.
		expect(rejectPath("reasoned", "9", 0).unfiled).toBe(9);
		expect(rejectPath("reasoned", "", 0).unfiled).toBe(0);
	});
});

describe("the bare count still works where it is chosen deliberately", () => {
	it("passes the number through on an order with no scrap records", () => {
		// Kept on Zafar's instruction: the exclusivity already makes it safe, and
		// it costs nothing unused. It is not the default and it is not promoted.
		expect(rejectPath("count", "4", 0)).toMatchObject({ path: "count", scrap_qty: 4 });
		expect(sentScrapQty("count", "4", 0)).toBe(4);
	});

	it("sends nothing rather than a zero when the box is untouched", () => {
		// `scrap_qty: 0` is not the same argument as no argument on the way into
		// `make_work_order_stock_entry`.
		expect(rejectPath("count", "", 0).scrap_qty).toBeUndefined();
		expect(rejectPath("count", "0", 0).scrap_qty).toBeUndefined();
	});

	it("never counts a negative as a reject", () => {
		expect(rejectPath("count", "-3", 0).scrap_qty).toBeUndefined();
	});

	it("leaves nothing unfiled, because the number rides along with the Finish", () => {
		expect(rejectPath("count", "4", 0).unfiled).toBe(0);
	});
});

/**
 * The Confirm Submit guard, pulled out of the shipped template and executed —
 * the same technique finishSweepGuard.spec.js uses on the same button.
 */
function disabledExpression(clickHandler) {
	const click = src.indexOf(`@click="${clickHandler}"`);
	expect(click, `no button bound to ${clickHandler}`).toBeGreaterThan(-1);
	const marker = ':disabled="';
	const start = src.lastIndexOf(marker, click);
	expect(start, `the ${clickHandler} button carries no :disabled binding`).toBeGreaterThan(-1);
	const bodyStart = start + marker.length;
	const end = src.indexOf('"', bodyStart);
	expect(end, "unterminated :disabled binding").toBeGreaterThan(bodyStart);
	return src.slice(bodyStart, end);
}

const EXPR = disabledExpression("confirmFinish");
const READY = { producedQty: 12, sweepPending: false, sweepAck: false, unfiledScrap: false };

function isDisabled(overrides = {}) {
	const scope = { ...READY, ...overrides };
	const fn = new Function(...Object.keys(scope), `return (${EXPR});`);
	return !!fn(...Object.values(scope));
}

describe("Finish waits for a reasoned reject to be filed", () => {
	it("is live on an ordinary order with nothing rejected", () => {
		expect(isDisabled()).toBe(false);
	});

	it("is held while the reject box holds a number no record has claimed", () => {
		expect(isDisabled({ unfiledScrap: true })).toBe(true);
	});

	it("still holds for the reasons it already held for", () => {
		// The guard grew a term; it did not lose one.
		expect(isDisabled({ producedQty: 0 })).toBe(true);
		expect(isDisabled({ sweepPending: true })).toBe(true);
	});
});

describe("the reasons are the catalogue's, never the mockup's", () => {
	it("asks the server for the Loss half of the reason list", () => {
		expect(src).toContain("list_stop_reasons");
		expect(src).toMatch(/kind:\s*"Loss"/);
	});

	it("hardcodes none of the four illustrative chips from the design", () => {
		// "Кривой рожок / Глазурь / Вес / Упаковка" show the SHAPE of the picker.
		// The taxonomy is `Stabler Stop Reason`, seeded, translated into five
		// languages, live on prod, and not yet reviewed by Zafar — so it is the
		// one thing this screen must not carry a second opinion about.
		expect(src).not.toMatch(/Кривой|Глазурь|Упаковка/);
	});
});

describe("a kiosk is one screen for a whole shift", () => {
	it("clears the previous order's reject state when the dialog opens", () => {
		// The same failure sweepAck had: state left over from the last order waves
		// the next one through. Here it would mean an order inheriting another
		// order's scrap-record count and hiding its own count box.
		const body = functionBody("openFinish");
		expect(body).toMatch(/rejectMode\.value\s*=\s*"reasoned"/);
		expect(body).toMatch(/scrapRecords\.value\s*=\s*0/);
	});

	it("asks what this order already has before the operator can type", () => {
		// Without this, an order scrapped on the previous shift offers the count
		// box, and the operator meets `_assert_no_scrap_record` after counting.
		// Awaited, not fired and forgotten: the answer decides which box renders.
		expect(functionBody("openFinish")).toMatch(/await\s+loadScrapOptions\(/);
		expect(functionBody("loadScrapOptions")).toContain("wo_scrap_options");
	});

	it("takes the record count from the server, not from what it filed itself", () => {
		// A count kept only in the browser is blind to the previous shift and to
		// the scrap screen, and both write records this guard must see.
		expect(functionBody("loadScrapOptions")).toMatch(/scrapRecords\.value\s*=/);
	});
});
