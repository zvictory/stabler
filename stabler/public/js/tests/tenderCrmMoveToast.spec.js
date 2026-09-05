import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/TenderCrm.vue"), "utf8");

/**
 * Measured 2026-09-05 RU walk (docs/uat/tender/2026-09-05-mikas-gercek-deneme-senaryosu.md
 * §G.21, §C1): one drag from "Закупки" to "Выиграно" toasted
 * "Перемещено в Выиграно" TWICE.
 *
 * `onDrop`'s only defence against a repeat is `card.stage === targetLaneId`,
 * checked and set in the same synchronous step — airtight against the SAME
 * `cards` array being read twice, but not against a `cards` reload landing
 * between two attempts: `load()` replaces `cards.value` with a brand new
 * array of brand new objects, so a stray second attempt for the same card
 * finds a FRESH object still at the pre-move stage, passes the guard again,
 * and re-submits — a second `move_deal_stage` call and a second identical
 * toast for what was one drag.
 *
 * The fix locks on the card NAME (not the object `cards.value` currently
 * hands back), checked before `cards` is even read, so it survives a reload
 * landing mid-flight. Executed, not grepped — same shape as
 * sourcingAddQuotationEvent.spec.js.
 */
function braceMatched(from) {
	let depth = 0;
	for (let i = from; i < src.length; i++) {
		if (src[i] === "{") depth++;
		else if (src[i] === "}" && --depth === 0) return src.slice(from, i + 1);
	}
	throw new Error("unterminated block");
}

function extractFunction(name) {
	let at = src.indexOf(`function ${name}(`);
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	// onDrop is `async function onDrop(...)`; include the modifier so the
	// extracted declaration keeps its `await`s valid.
	if (src.slice(Math.max(0, at - 6), at) === "async ") at -= 6;
	const braceStart = src.indexOf("{", at);
	return src.slice(at, braceStart) + braceMatched(braceStart);
}

// onDrop closes over dragOverLane/dragCardName (drag state), isPostWinLane,
// movingCards (the new in-flight lock), cards, call, toast, t and stageLabel.
function build({ dragOverLane, dragCardName, isPostWinLane, movingCards, cards, call, toast, t, stageLabel }) {
	const factory = new Function(
		"dragOverLane",
		"dragCardName",
		"isPostWinLane",
		"movingCards",
		"cards",
		"call",
		"toast",
		"t",
		"stageLabel",
		`${extractFunction("onDrop")}\nreturn onDrop;`
	);
	return factory(dragOverLane, dragCardName, isPostWinLane, movingCards, cards, call, toast, t, stageLabel);
}

function harness(overrides = {}) {
	const toastCalls = [];
	const stubToast = {
		success: (msg) => toastCalls.push(["success", msg]),
		error: (msg) => toastCalls.push(["error", msg]),
	};
	let apiCalls = 0;
	const cardsBox = { value: [{ name: "CRM-DEAL-2026-00015", stage: "sourcing" }] };
	const state = {
		dragOverLane: { value: "" },
		dragCardName: { value: "CRM-DEAL-2026-00015" },
		isPostWinLane: () => false,
		movingCards: new Set(),
		cards: cardsBox,
		call: async () => {
			apiCalls++;
			return {};
		},
		toast: stubToast,
		t: (s) => s,
		stageLabel: (id) => id,
		...overrides,
	};
	const onDrop = build(state);
	return { onDrop, toastCalls, apiCallCount: () => apiCalls, cardsBox, state };
}

describe("TenderCrm's onDrop toasts exactly once per accepted move", () => {
	it("a normal single drop toasts once", async () => {
		const { onDrop, toastCalls, apiCallCount } = harness();
		await onDrop("won");
		expect(apiCallCount()).toBe(1);
		expect(toastCalls).toEqual([["success", "Moved to won"]]);
	});

	it("a stray second drop landing while a reload replaced `cards` mid-flight still toasts once", async () => {
		// This is the gap `card.stage === targetLaneId` alone does not cover: a
		// `load()` in between hands back a FRESH object for the same name, still
		// at the OLD stage, so the stage check alone would pass a second time.
		// Both drops carry their own dragstart (dragCardName re-armed) — same as
		// two real drop dispatches landing for what was reported as one drag.
		const { onDrop, toastCalls, apiCallCount, cardsBox, state } = harness();

		state.dragCardName.value = "CRM-DEAL-2026-00015";
		const p1 = onDrop("won");
		// A reload completes, and a second drop of the same card arrives, before
		// the first move has settled.
		cardsBox.value = [{ name: "CRM-DEAL-2026-00015", stage: "sourcing" }];
		state.dragCardName.value = "CRM-DEAL-2026-00015";
		const p2 = onDrop("won");

		await Promise.all([p1, p2]);

		expect(apiCallCount(), "move_deal_stage was called more than once for one drag").toBe(1);
		expect(toastCalls, "the success toast fired more than once for one drag").toEqual([
			["success", "Moved to won"],
		]);
	});

	it("a genuinely new drag, once the first move has settled, is a real second move", async () => {
		// The lock must not outlive the move it guards — once settled, dragging
		// the same card again (a real, separate action) should work normally.
		const { onDrop, toastCalls, apiCallCount, state } = harness();
		state.dragCardName.value = "CRM-DEAL-2026-00015";
		await onDrop("won");
		state.dragCardName.value = "CRM-DEAL-2026-00015";
		await onDrop("lost");
		expect(apiCallCount()).toBe(2);
		expect(toastCalls).toEqual([
			["success", "Moved to won"],
			["success", "Moved to lost"],
		]);
	});
});
