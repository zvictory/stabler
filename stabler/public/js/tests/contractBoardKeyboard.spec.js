import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/sales/SalesOrderBoard.vue"), "utf8");

/**
 * The contract board can be operated without a mouse — prompt 18's C10 and C11.
 *
 * Measured on the whole file 2026-09-02: zero `aria-*`, zero `tabindex`, zero
 * keyboard handlers. The only way to move a contract between stages was an HTML5
 * drag, and the same element carried `draggable="true"` and
 * `@click="openSo(c.name)"` with no guard between them — so a press that tried
 * to move a card and did not travel far enough to start a drag opened the Sales
 * Order instead. The user reached for the card and left the board.
 *
 * The sibling kanban (TenderCrm.vue:574-580) already establishes half the
 * answer: `role="button"` + `tabindex="0"` + Enter/Space on a plain div, chosen
 * over a real <button> because Firefox will not drag one. It does NOT establish
 * a keyboard MOVE — no screen in this repository had one — so the arrow keys
 * below are new, and the rules they follow are asserted here rather than left to
 * the next reader to infer.
 *
 * DOM-less per vitest.config.mjs: the handlers are lifted out of the source and
 * run for real against fakes, because "the card moves and gets its focus back"
 * is a claim about behaviour that no source-text match can make.
 */

/** Source of one top-level function, from its declaration to its closing brace. */
function fnSrc(name) {
	const m = src.match(new RegExp(`^(?:async )?function ${name}\\([\\s\\S]*?^\\}`, "m"));
	expect(m, `SalesOrderBoard.vue has no top-level ${name}()`).not.toBeNull();
	return m[0];
}

/**
 * Source of one top-level `const`/`let` declaration.
 *
 * The click guard's state is LIFTED, not re-declared in the harness: supplying
 * `pressAt` as a scope parameter would leave these tests green against a
 * component that no longer declares it. Same reason contractBoardReload.spec.js
 * lifts `let reqToken = 0;` rather than inventing one.
 */
function declSrc(name) {
	const m = src.match(new RegExp(`^(?:const|let) ${name} = .*;$`, "m"));
	expect(m, `SalesOrderBoard.vue declares no ${name}`).not.toBeNull();
	return m[0];
}

/** Lift the named functions (and any state they close over) into one scope. */
function lift(scope, names, state = []) {
	const keys = Object.keys(scope);
	const body = [...state.map(declSrc), ...names.map(fnSrc)].join("\n");
	return new Function(...keys, `${body}\nreturn {${names.join(",")}};`)(...keys.map((k) => scope[k]));
}

/** The state every click-guard handler closes over. */
const CLICK_STATE = ["CLICK_SLOP", "pressAt", "suppressClick"];

/** The card's opening tag, quote-aware so an attribute value cannot end it. */
function cardTag() {
	const at = src.indexOf('v-for="c in cardsByStage');
	expect(at, "the card v-for has moved").toBeGreaterThan(-1);
	const open = src.lastIndexOf("<", at);
	let quote = "";
	for (let i = open; i < src.length; i++) {
		const ch = src[i];
		if (quote) {
			if (ch === quote) quote = "";
			continue;
		}
		if (ch === '"' || ch === "'") quote = ch;
		else if (ch === ">") return src.slice(open, i + 1);
	}
	throw new Error("the card's opening tag is unterminated");
}

/** Four stages and one card sitting on the second of them. */
function harness({ reject = false } = {}) {
	const stages = { value: [{ name: "New" }, { name: "Procurement" }, { name: "Delivery" }, { name: "Paid" }] };
	const cards = { value: [{ name: "SO-1", stage: "Procurement" }] };
	const sent = [];
	const errors = [];
	const focused = [];
	const opened = [];
	const scope = {
		cards,
		stages,
		dragCard: { value: "" },
		dragOver: { value: "" },
		t: (s) => s,
		toast: { error: (m) => errors.push(m) },
		openSo: (name) => opened.push(name),
		nextTick: async () => {},
		call: async (method, args) => {
			sent.push({ method, args });
			if (reject) throw new Error("Server said no.");
			return {};
		},
		document: {
			querySelector: (sel) => ({ focus: () => focused.push(sel) }),
		},
	};
	return { scope, cards, stages, sent, errors, focused, opened };
}

describe("a card can be reached and opened from the keyboard", () => {
	it("makes the card focusable and announces what it is", () => {
		// WHAT WOULD MAKE THIS FAIL: the card staying a plain <div>. Without
		// tabindex it is not in the tab order at all, so a keyboard user cannot
		// reach the card — every other assertion in this file describes a
		// capability they could never invoke. role="button" over <button> is the
		// sibling kanban's own choice (TenderCrm.vue:568): Firefox will not drag
		// a real button.
		const tag = cardTag();
		expect(tag).toMatch(/tabindex="0"/);
		expect(tag).toMatch(/role="button"/);
	});

	it("tells a screen reader that the arrows do something", () => {
		// WHAT WOULD MAKE THIS FAIL: shipping the arrow keys with no label. A
		// focusable div announced as "button" and nothing else gives the reader
		// no reason to press an arrow — an affordance nobody is told about is
		// the same as no affordance, and this is the only place the board can
		// say it without putting a hint on every card for everyone.
		expect(cardTag()).toMatch(/:aria-label=/);
	});

	it("opens the order on Enter and on Space", () => {
		// WHAT WOULD MAKE THIS FAIL: binding only @click. A div does not
		// synthesise a click from Enter the way a <button> does, so the card
		// would be focusable and inert. `.prevent` on Space is not decoration:
		// without it the browser scrolls the page instead.
		const tag = cardTag();
		expect(tag).toMatch(/@keydown\.enter\.prevent="[^"]*openSo\(/);
		expect(tag).toMatch(/@keydown\.space\.prevent="[^"]*openSo\(/);
	});
});

describe("← and → move the card between stages", () => {
	it("binds both arrows, and stops the board scrolling instead", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping `.prevent`. The board is a
		// horizontally scrolling strip; an unprevented ArrowRight scrolls it,
		// so the card would sit still while the screen slid sideways — the
		// reader would read that as "the move did not work".
		const tag = cardTag();
		expect(tag).toMatch(/@keydown\.arrow-left\.prevent="[^"]*moveCardByKey\(c\.name, -1\)/);
		expect(tag).toMatch(/@keydown\.arrow-right\.prevent="[^"]*moveCardByKey\(c\.name, 1\)/);
	});

	it("really reaches Vue's key matcher, measured through its own compiler", async () => {
		// WHAT WOULD MAKE THIS FAIL: a modifier Vue does not recognise. `.arrow-left`
		// is a KEY NAME in kebab-case — the runtime compares `hyphenate(event.key)`,
		// so "ArrowLeft" matches. NOTHING errors on a typo: `@keydown.leftarrow`
		// compiles just as happily to `withKeys(…, ["leftarrow"])` and then never
		// fires, and every source-text assertion in this file would stay green while
		// the feature did nothing at all. This is the one link in the chain that the
		// component's own source cannot vouch for.
		const { compile } = await import("@vue/compiler-dom");
		const { hyphenate } = await import("@vue/shared");
		const code = compile(`${cardTag()}</div>`, { mode: "module" }).code;
		expect(code, "the left arrow does not compile to a key matcher").toContain('["arrow-left"]');
		expect(code, "the right arrow does not compile to a key matcher").toContain('["arrow-right"]');
		expect(hyphenate("ArrowLeft")).toBe("arrow-left");
		expect(hyphenate("ArrowRight")).toBe("arrow-right");
	});

	it("moves one stage in the direction pressed", async () => {
		// WHAT WOULD MAKE THIS FAIL: moving by index into the wrong list, or by
		// more than one. One press, one stage, in the direction the reader is
		// looking — the board is drawn left to right and the key names the
		// direction on screen.
		const h = harness();
		const { moveCardByKey } = lift(h.scope, ["moveCard", "moveCardByKey"]);
		await moveCardByKey("SO-1", 1);
		expect(h.sent).toEqual([
			{ method: "stabler.api.tender.move_so_stage", args: { name: "SO-1", stage: "Delivery" } },
		]);
		expect(h.cards.value[0].stage).toBe("Delivery");
	});

	it("moves the other way too", async () => {
		const h = harness();
		const { moveCardByKey } = lift(h.scope, ["moveCard", "moveCardByKey"]);
		await moveCardByKey("SO-1", -1);
		expect(h.sent[0].args.stage).toBe("New");
	});

	it("stops at both ends instead of wrapping around", async () => {
		// WHAT WOULD MAKE THIS FAIL: `(at + delta + n) % n`. A card at *Paid*
		// reappearing at *New* is a data change nobody asked for, and on a board
		// wider than the screen the reader would not even see where it went. An
		// arrow at the end of the row does nothing, which is what every other
		// list in this app does.
		const first = harness();
		first.cards.value[0].stage = "New";
		await lift(first.scope, ["moveCard", "moveCardByKey"]).moveCardByKey("SO-1", -1);
		expect(first.sent, "a card at the first stage moved left").toEqual([]);
		expect(first.cards.value[0].stage).toBe("New");

		const last = harness();
		last.cards.value[0].stage = "Paid";
		await lift(last.scope, ["moveCard", "moveCardByKey"]).moveCardByKey("SO-1", 1);
		expect(last.sent, "a card at the last stage moved right").toEqual([]);
		expect(last.cards.value[0].stage).toBe("Paid");
	});

	it("gives the card its focus back where it landed", async () => {
		// WHAT WOULD MAKE THIS FAIL: not restoring focus. The card is unmounted
		// from one column's v-for and mounted in another's, so focus falls back
		// to <body>. Without this, a reader moving a card three stages has to
		// tab in from the top of the document twice — the feature would work
		// once and then punish anyone who used it.
		const h = harness();
		const { moveCardByKey } = lift(h.scope, ["moveCard", "moveCardByKey"]);
		await moveCardByKey("SO-1", 1);
		expect(h.focused.length, "focus was not restored after the move").toBe(1);
		expect(h.focused[0]).toContain("SO-1");
	});

	it("does not ask the server when there is nothing to move", async () => {
		// WHAT WOULD MAKE THIS FAIL: firing a request for a card that is not on
		// the board, or for a stage the card is already on. A move_so_stage that
		// changes nothing still writes, still bumps `modified`, and still costs
		// a round trip on every stray keypress.
		const h = harness();
		const { moveCardByKey } = lift(h.scope, ["moveCard", "moveCardByKey"]);
		await moveCardByKey("SO-NOT-HERE", 1);
		expect(h.sent).toEqual([]);
	});
});

describe("the keyboard move and the drop are one move", () => {
	it("talks to the server in exactly one place", () => {
		// WHAT WOULD MAKE THIS FAIL: the arrow handler growing its own copy of
		// the optimistic write. Two copies means two rollbacks, and the one
		// nobody exercises is the one that rots — the drop path's rollback is
		// the only reason a refused move does not leave the card in a stage the
		// server never accepted.
		expect(src.match(/move_so_stage/g)?.length, "move_so_stage appears more than once").toBe(1);
	});

	it("rolls the card back and says so when the server refuses", async () => {
		// WHAT WOULD MAKE THIS FAIL: an optimistic write with no rollback. The
		// keyboard path now depends on this, so it is asserted here and not left
		// to the drop path's own tests: a card left in a stage the server
		// rejected reads as saved and is not.
		const h = harness({ reject: true });
		const { moveCardByKey } = lift(h.scope, ["moveCard", "moveCardByKey"]);
		await moveCardByKey("SO-1", 1);
		expect(h.cards.value[0].stage, "the card kept a stage the server refused").toBe("Procurement");
		expect(h.errors).toEqual(["Server said no."]);
	});

	it("still moves the card when it is dropped", async () => {
		// WHAT WOULD MAKE THIS FAIL: the refactor breaking the mouse path while
		// making the keyboard one work. The drop is how the board is used today.
		const h = harness();
		const lifted = lift(h.scope, ["moveCard", "onDrop"]);
		h.scope.dragCard.value = "SO-1";
		await lifted.onDrop("Paid");
		expect(h.sent[0].args).toEqual({ name: "SO-1", stage: "Paid" });
	});
});

describe("a press that tried to move the card does not navigate", () => {
	it("does not open the order when the pointer travelled", () => {
		// WHAT WOULD MAKE THIS FAIL: no distance guard — C11 exactly. A press
		// that nudges the card a few pixels never reaches the browser's drag
		// threshold, so no drag starts, and the click that follows opened the
		// Sales Order. The reader tried to move a contract and left the board.
		// On a touch screen it is worse: `draggable` does nothing there, so
		// EVERY attempted drag was a tap that navigated away.
		const h = harness();
		const { onCardPointerDown, onCardClick } = lift(h.scope, ["onCardPointerDown", "onCardClick"], CLICK_STATE);
		onCardPointerDown({ clientX: 100, clientY: 100 });
		onCardClick("SO-1", { clientX: 140, clientY: 100 });
		expect(h.opened, "a press that travelled 40px still navigated").toEqual([]);
	});

	it("still opens the order on an ordinary click", () => {
		// WHAT WOULD MAKE THIS FAIL: a guard so tight that nothing gets through.
		// A real click never lands on exactly the pixel it started on — a hand
		// on a trackpad moves a pixel or two — so the guard needs slack, and a
		// guard with no slack would make the card unopenable by mouse.
		const h = harness();
		const { onCardPointerDown, onCardClick } = lift(h.scope, ["onCardPointerDown", "onCardClick"], CLICK_STATE);
		onCardPointerDown({ clientX: 100, clientY: 100 });
		onCardClick("SO-1", { clientX: 101, clientY: 100 });
		expect(h.opened).toEqual(["SO-1"]);
	});

	it("does not open the order after a drag that ended where it began", () => {
		// WHAT WOULD MAKE THIS FAIL: trusting the browser not to fire a click
		// after a drag. The specification says it does not; that is one more
		// browser behaviour this board would be betting on, and the bet costs
		// the reader a navigation they did not ask for when it loses.
		const h = harness();
		const lifted = lift(h.scope, ["onCardPointerDown", "onCardDragStart", "onCardClick"], CLICK_STATE);
		lifted.onCardPointerDown({ clientX: 100, clientY: 100 });
		lifted.onCardDragStart("SO-1", { dataTransfer: {} });
		lifted.onCardClick("SO-1", { clientX: 100, clientY: 100 });
		expect(h.opened).toEqual([]);
	});

	it("opens the order on a keyboard activation, which has no coordinates", () => {
		// WHAT WOULD MAKE THIS FAIL: a guard that reads clientX off an event
		// that has none. Enter and Space route around the click path entirely,
		// but if they ever did not, a synthesised click reports 0,0 — and a
		// guard measuring from a stale press would refuse the one activation
		// this whole change exists to add.
		const h = harness();
		const { onCardClick } = lift(h.scope, ["onCardPointerDown", "onCardClick"], CLICK_STATE);
		onCardClick("SO-1", { clientX: 0, clientY: 0 });
		expect(h.opened).toEqual(["SO-1"]);
	});

	it("routes the card's click through the guard rather than straight to openSo", () => {
		// WHAT WOULD MAKE THIS FAIL: the guard existing in the script and the
		// template still calling openSo directly — the fix present, wired to
		// nothing, and every test above it still green because they call the
		// lifted function themselves.
		const tag = cardTag();
		expect(tag).toMatch(/@pointerdown="[^"]*onCardPointerDown\(/);
		expect(tag).toMatch(/@click="[^"]*onCardClick\(c\.name/);
		expect(/@click="openSo\(/.test(tag), "the card still navigates on a raw click").toBe(false);
	});
});
