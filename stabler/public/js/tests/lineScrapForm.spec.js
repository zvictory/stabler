import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/manufacturing/LineScrap.vue"), "utf8");

/**
 * The three things the loss log has to get right before it has recorded anything.
 *
 * 1. NOT CONFIGURED IS A SCREEN, NOT A REFUSAL. `get_scrap_warehouse` throws by
 *    design — "a scrap record that skipped its draft because nothing was
 *    configured would recreate exactly that split, and it would do it silently" —
 *    and as of 2026-08-29 no tenant has named a scrap warehouse. So on every site
 *    this screen ships to, the first thing it can do is throw. The operator who
 *    meets that throw cannot fix it: Stabler Manufacturing Settings is a
 *    manager's document. The screen therefore has to read the answer out of
 *    `wo_scrap_options` and say what is missing and who fixes it, before anything
 *    is typed.
 *
 * 2. AN ITEM WITH NOTHING IN WIP MUST NOT BE OFFERED. `validate_scrap` refuses it
 *    ("{0} has nothing in WIP on this order to scrap"), and a picker that lists
 *    it is a picker whose entries are a coin toss.
 *
 * 3. THE DRAFT'S NAME REACHES THE OPERATOR. `log_line_scrap` returns
 *    `stock_entry` for one stated reason — "the operator has to be told that a
 *    stock document now exists in somebody else's queue". A success message that
 *    drops it turns a two-party handover into a silent one.
 *
 * Executed, not grepped, for the reason manufacturingTabGates.spec.js gives:
 * `expect(src).toContain("scrap_warehouse")` passes just as happily on a
 * readiness check wired backwards. @vue/test-utils is not a devDependency here.
 */
function fnSource(name) {
	const start = src.indexOf(`function ${name}(`);
	expect(start, `${name}() is not in the shipped component`).toBeGreaterThan(-1);
	const end = src.indexOf("\n}", start);
	expect(end, `${name}(): unterminated body`).toBeGreaterThan(start);
	return src.slice(start, end + 2);
}

function build(name, extra = "") {
	// `t` is stubbed to echo its key with the params appended, so an assertion can
	// see whether an argument reached the string without depending on any
	// catalogue. The real `t` falls back to the source string the same way.
	const stub = 'const t = (s, p) => (p ? s + " " + Object.values(p).join(" ") : s);';
	return new Function(`${stub}\n${extra}\n${fnSource(name)}\nreturn ${name};`)();
}

const scrapReadiness = build("scrapReadiness");
const recordedNotice = build("recordedNotice");

const IN_WIP = { item_code: "RAW-MLK", item_name: "Milk", uom: "Kg", available: 40 };
const EMPTY = { item_code: "RAW-SGR", item_name: "Sugar", uom: "Kg", available: 0 };

describe("a site with no scrap warehouse is told so, not thrown at", () => {
	it("reports the missing setting when the endpoint returns none", () => {
		expect(scrapReadiness({ scrap_warehouse: null, items: [IN_WIP] })).toBe("unconfigured");
	});

	it("reports it as unconfigured even when there is plenty in WIP to scrap", () => {
		// The order of the two answers matters and matches the server's:
		// `validate` reads the warehouse BEFORE it checks the quantity, so
		// "your site was never set up" is never dressed up as "your number is wrong".
		expect(scrapReadiness({ scrap_warehouse: "", items: [IN_WIP, IN_WIP] })).toBe("unconfigured");
	});

	it("does not claim readiness before the endpoint has answered", () => {
		// Between picking an order and its options arriving, an optimistic "ready"
		// renders the form for one frame and invites a number into it.
		expect(scrapReadiness(null)).toBe("unknown");
	});
});

describe("a configured site is offered the form only when there is something to lose", () => {
	it("is ready when an item still stands in WIP", () => {
		expect(scrapReadiness({ scrap_warehouse: "Scrap - A", items: [EMPTY, IN_WIP] })).toBe("ready");
	});

	it("says the order holds nothing rather than offering an item the server refuses", () => {
		expect(scrapReadiness({ scrap_warehouse: "Scrap - A", items: [EMPTY] })).toBe("nothing-in-wip");
	});

	it("says the same for an order that never carried materials", () => {
		expect(scrapReadiness({ scrap_warehouse: "Scrap - A", items: [] })).toBe("nothing-in-wip");
	});
});

describe("the draft the record just created is named to the operator", () => {
	it("names the stock entry, because somebody else has to submit it", () => {
		const msg = recordedNotice({ name: "SLS-0007", stock_entry: "MAT-STE-0042" });
		expect(msg).toContain("MAT-STE-0042");
	});

	it("still confirms the record when no draft came back", () => {
		// Not reachable today — `after_insert` writes the draft in the same
		// transaction — but a message that renders "undefined" on a shop-floor
		// terminal is worse than one that says less.
		const msg = recordedNotice({ name: "SLS-0007", stock_entry: null });
		expect(msg).not.toContain("undefined");
		expect(msg.length).toBeGreaterThan(0);
	});
});

/**
 * The Record button's own guard, pulled out of the shipped template and executed
 * — the same technique operatorWriteOffGate.spec.js uses, and for the same
 * reason: every state it refuses is one the server also refuses, and a shop-floor
 * terminal should not learn that from a round trip and a red box.
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

const EXPR = disabledExpression("save");

const READY = {
	saving: false,
	readiness: "ready",
	form: { work_order: "WO-9", item_code: "RAW-MLK", qty: "3", reason: "Spillage", note: "" },
};

function isDisabled(overrides = {}) {
	const scope = { ...READY, ...overrides };
	const fn = new Function(...Object.keys(scope), `return (${EXPR});`);
	return !!fn(...Object.values(scope));
}

describe("the Record button refuses what the server would refuse", () => {
	it("is live once an order, an item, a reason and a quantity are all present", () => {
		expect(isDisabled()).toBe(false);
	});

	it("refuses a record with no reason — the whole point of this log", () => {
		// `_assert_loss_reason` throws on an empty reason, and "брак с причиной"
		// without the причина is the bare `scrap_qty` box that went unused on
		// 3757 entries.
		expect(isDisabled({ form: { ...READY.form, reason: "" } })).toBe(true);
	});

	it("refuses a record with no item", () => {
		expect(isDisabled({ form: { ...READY.form, item_code: "" } })).toBe(true);
	});

	it("refuses a record with no Work Order", () => {
		// `_require_work_order`: without it there is no defensible source
		// warehouse for the transfer.
		expect(isDisabled({ form: { ...READY.form, work_order: "" } })).toBe(true);
	});

	it("refuses zero — a double-tap, not a loss", () => {
		expect(isDisabled({ form: { ...READY.form, qty: "0" } })).toBe(true);
		expect(isDisabled({ form: { ...READY.form, qty: "" } })).toBe(true);
	});

	it("refuses a negative quantity, which would move stock back onto the line", () => {
		expect(isDisabled({ form: { ...READY.form, qty: "-2" } })).toBe(true);
	});

	it("is dead on a site with no scrap warehouse, however complete the form is", () => {
		expect(isDisabled({ readiness: "unconfigured" })).toBe(true);
	});

	it("is dead while a record is already being written", () => {
		expect(isDisabled({ saving: true })).toBe(true);
	});
});
