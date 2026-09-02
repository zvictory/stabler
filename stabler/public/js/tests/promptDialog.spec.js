import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve as pathResolve } from "path";
import { fileURLToPath } from "url";
import { useConfirm } from "../composables/useConfirm.js";

const here = dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(pathResolve(here, "..", rel), "utf8");
const host = read("components/ConfirmHost.vue");
const board = read("pages/sales/SalesOrderBoard.vue");

/**
 * Asking the user for a name uses the app's own dialog — prompt 18, C18.
 *
 * `addStage` called `window.prompt`. S8's complaint was the asymmetry, and it is
 * the sharpest way to put it: this same file already imports `useConfirm()` and
 * uses it for DELETE. The destructive action got the house dialog and the
 * creative one got the browser's.
 *
 * `window.prompt` cannot be styled, cannot be translated below the message
 * string (its OK/Cancel come from the browser's locale, not the app's four),
 * offers no validation before submission, and some browsers suppress it
 * outright — in which case it returns null and the stage is silently never
 * created.
 *
 * Built ON `useConfirm` rather than beside it. ConfirmHost.vue is 130 lines of
 * focus management, Escape handling and a tab trap; a parallel PromptHost would
 * be a second copy of all of it, and this repository has already measured what
 * that costs (four divergent copies of one exclude list). One host, two entry
 * points, and `confirm()`'s own behaviour is asserted here too so that adding
 * the second one cannot quietly change the first.
 *
 * Twelve call sites across the app still use `window.prompt`; only this one is
 * wired. The rest are outside C18.
 */

describe("prompt() resolves what the user typed", () => {
	it("hands back the text, trimmed", async () => {
		// WHAT WOULD MAKE THIS FAIL: resolving the raw value. `addStage` used to
		// trim what window.prompt returned; the dialog owns that now, so a name
		// typed with a trailing space becomes a stage whose name has one — and
		// so_stage_delete matches on the name.
		const { currentConfirm, prompt } = useConfirm();
		const answer = prompt({ title: "New stage name" });
		currentConfirm.value.input.text = "  Handover  ";
		currentConfirm.value.resolve("  Handover  ");
		expect(await answer).toBe("Handover");
	});

	it("hands back null when the user backs out, not an empty string", async () => {
		// WHAT WOULD MAKE THIS FAIL: collapsing cancel and "typed nothing" into
		// one answer. They are different intentions and only one of them should
		// ever be reported to the user as a failure. window.prompt got this right
		// (null vs "") and it would be an odd thing to lose while replacing it.
		const { currentConfirm, prompt } = useConfirm();
		const answer = prompt({ title: "New stage name" });
		currentConfirm.value.resolve(false);
		expect(await answer).toBeNull();
	});

	it("clears itself so the next dialog is not the last one", async () => {
		// WHAT WOULD MAKE THIS FAIL: leaving `currentConfirm` set. The host
		// renders on truthiness, so a stale value is a modal that never closes.
		const { currentConfirm, prompt } = useConfirm();
		const answer = prompt({ title: "New stage name" });
		currentConfirm.value.resolve("x");
		await answer;
		expect(currentConfirm.value).toBeNull();
	});

	it("carries an input descriptor that a plain confirm does not", async () => {
		// WHAT WOULD MAKE THIS FAIL: the host having no way to tell the two
		// apart. `input` is the whole switch: present means draw a field, absent
		// means the dialog is exactly what it was before this change.
		const { currentConfirm, prompt, confirm } = useConfirm();
		prompt({ title: "New stage name", placeholder: "Handover" });
		expect(currentConfirm.value.input).toMatchObject({ text: "", placeholder: "Handover" });
		currentConfirm.value.resolve(false);

		confirm({ title: "Delete stage?", body: "Paid" });
		expect(currentConfirm.value.input).toBeUndefined();
		currentConfirm.value.resolve(false);
	});
});

describe("confirm() still does exactly what it did", () => {
	it("resolves true and false, not a string", async () => {
		// WHAT WOULD MAKE THIS FAIL: normalising every answer through the
		// prompt's rule. Every existing caller in the app reads the result as a
		// boolean; turning `true` into `null` would make each of them read as
		// "cancelled" and silently stop working.
		const { currentConfirm, confirm } = useConfirm();
		const yes = confirm({ title: "Delete stage?" });
		currentConfirm.value.resolve(true);
		expect(await yes).toBe(true);

		const no = confirm({ title: "Delete stage?" });
		currentConfirm.value.resolve(false);
		expect(await no).toBe(false);
	});
});

describe("the host draws the field and knows what to do with it", () => {
	it("renders an input only when one was asked for", () => {
		// WHAT WOULD MAKE THIS FAIL: an unconditional field. Every confirm in the
		// app shares this host; a stray empty text box under "Delete stage?"
		// would appear on all of them.
		expect(host).toMatch(/v-if="currentConfirm\.input"/);
		expect(host).toMatch(/v-model="currentConfirm\.input\.text"/);
	});

	it("focuses the field rather than a button", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving the existing focus rule alone. A
		// native prompt puts the caret in the field; a dialog that focuses OK
		// instead makes the user reach for the mouse to do the one thing the
		// dialog exists for.
		expect(host).toMatch(/inputBox/);
		expect(host).toMatch(/inputBox\.value\.focus\(\)/);
	});

	it("submits on Enter through the same path as the button", () => {
		// WHAT WOULD MAKE THIS FAIL: the Enter handler still resolving `true`.
		// That was correct for a confirm and is wrong here — the caller would
		// receive a boolean where it expected a name, and `true` is not a string,
		// so prompt() would report it as a cancellation.
		expect(host).toMatch(/function submit\(\)/);
		expect(host).toMatch(/@click="submit\(\)"/);
		const enter = host.slice(host.indexOf('e.key === "Enter"'), host.indexOf("Tab"));
		expect(enter).toMatch(/submit\(\)/);
	});

	it("refuses to submit a required field that is empty", () => {
		// WHAT WOULD MAKE THIS FAIL: no validation. window.prompt had none
		// either, which is why `addStage` guarded with `if (!name) return;` — a
		// dialog that simply closes on OK, having done nothing, is the same
		// silence one layer up. Here the button is disabled instead.
		expect(host).toMatch(/:disabled=/);
		expect(host).toMatch(/currentConfirm\.input\.required/);
	});

	it("keeps the field inside the tab cycle", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving the trap on the two buttons. Tab
		// from the field would jump to the page behind the modal, which is the
		// thing a tab trap exists to prevent — and the field is now the first
		// thing focused, so it is the most likely place to Tab from.
		//
		// Anchored to `onMounted(` — the CALL. The first version cut at
		// `onMounted`, which matches the import on line 2, so the slice ran
		// backwards and came out empty and the assertion could not fail. A slice
		// that silently yields "" is a test that passes on nothing.
		const start = host.indexOf('e.key === "Tab"');
		const end = host.indexOf("onMounted(", start);
		expect(start, "the tab trap has moved").toBeGreaterThan(-1);
		expect(end, "no onMounted( after the tab trap").toBeGreaterThan(start);
		expect(host.slice(start, end)).toMatch(/inputBox/);
	});
});

describe("the board asks through the app, not the browser", () => {
	it("no longer calls window.prompt", () => {
		// WHAT WOULD MAKE THIS FAIL: the native dialog coming back. Some
		// browsers suppress it outright — then it returns null, `addStage`
		// returns early, and the stage is silently never created with nothing on
		// screen to say so.
		//
		// A CALL, not a mention: the comment above `addStage` names what was
		// replaced, and a test that cannot tell the two apart forces the code to
		// stop explaining itself in order to stay green.
		expect(/window\.prompt\(/.test(board), "window.prompt( is back on the board").toBe(false);
	});

	it("uses the house dialog it already imported for delete", () => {
		// WHAT WOULD MAKE THIS FAIL: importing a second dialog. S8's complaint
		// was the asymmetry inside this one file — delete got the house dialog
		// and create got the browser's — so the fix has to be the same dialog,
		// not a third one.
		expect(board).toMatch(/const \{ confirm, prompt \} = useConfirm\(\)/);
		expect(board).toMatch(/await prompt\(/);
	});

	it("still refuses an empty name at the call site", () => {
		// WHAT WOULD MAKE THIS FAIL: trusting the dialog's own validation alone.
		// prompt() resolves null on cancel, and null is not a name — the guard
		// that was there for window.prompt is still the guard for this.
		const fn = board.match(/^async function addStage\(\)[\s\S]*?^\}/m);
		expect(fn, "addStage has moved").not.toBeNull();
		expect(fn[0]).toMatch(/if \(!name\) return;/);
	});
});
