import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

vi.mock("../composables/i18n.js", () => ({ t: (s) => s }));
const { applyNumpadKey, sanitizeNumeric } = await import("../composables/numpad.js");

describe("applyNumpadKey", () => {
	it("builds a number one tap at a time", () => {
		expect(["1", "2", "0"].reduce(applyNumpadKey, "")).toBe("120");
	});

	// The shift's output is typed here and nowhere else. "1.2.5" is not a number:
	// it reaches the API as NaN, the stock entry fails, and the operator has
	// already left the terminal. A calculator ignores the second dot; so does this.
	it("refuses a second decimal point", () => {
		expect(applyNumpadKey("1.2", ".")).toBe("1.2");
	});

	// Tapping "." first means "nought point something". A bare "." parses to NaN.
	it("opens a decimal with the zero the operator did not type", () => {
		expect(applyNumpadKey("", ".")).toBe("0.");
	});

	// A wall-mounted display reading "0450" looks like a typo, and operators
	// clear and retype it — so the leading zero goes when a digit follows it.
	it("drops a placeholder zero once a real digit arrives", () => {
		expect(applyNumpadKey("0", "5")).toBe("5");
	});

	// ...but not when the zero is the whole point: 0.5 kg of flavouring is a
	// quantity these orders actually carry.
	it("keeps the zero that belongs to a decimal", () => {
		expect(applyNumpadKey("0.", "5")).toBe("0.5");
	});

	it("backspaces one character", () => {
		expect(applyNumpadKey("12.5", "back")).toBe("12.");
	});

	// Backspace past the start is the most-tapped key on a kiosk. It must be a
	// no-op, not an empty-string crash or a stray "-".
	it("survives backspace on an empty field", () => {
		expect(applyNumpadKey("", "back")).toBe("");
	});

	it("clears the whole field", () => {
		expect(applyNumpadKey("123.45", "clear")).toBe("");
	});
});

describe("sanitizeNumeric", () => {
	// The field stays typeable so an office user on a laptop is not locked out
	// of a screen the shop floor taps. That keyboard can produce anything.
	it("keeps digits and the first decimal point, drops the rest", () => {
		expect(sanitizeNumeric("1a2.3.4")).toBe("12.34");
	});

	it("passes a clean number through untouched", () => {
		expect(sanitizeNumeric("0.750")).toBe("0.750");
	});
});

const here = dirname(fileURLToPath(import.meta.url));
const board = readFileSync(
	resolve(here, "../pages/manufacturing/ManufacturingOperatorBoard.vue"),
	"utf8",
);
const pad = readFileSync(resolve(here, "../components/NumPad.vue"), "utf8");

describe("operator board quantity entry", () => {
	// The terminal is wall-mounted and operated with gloves. A native number
	// spinner puts two 12-pixel arrows on that wall, and on a locked-down
	// Android kiosk it is a coin toss whether any soft keyboard appears at all.
	it("puts an on-screen numpad on the finish dialog", () => {
		expect(board).toMatch(/<NumPad\b/);
		expect(board).toMatch(/import NumPad from "\.\.\/\.\.\/components\/NumPad\.vue";/);
	});

	// A buffer mid-decimal ("1.") is not a valid `type=number` value — the
	// browser blanks the field as the operator taps the dot.
	it("keeps the quantity fields typeable rather than native number spinners", () => {
		const fields = (board.match(/<input\b[\s\S]*?\/>/g) || []).filter((tag) =>
			/producedQty|scrapQty/.test(tag),
		);
		expect(fields.length).toBe(2);
		for (const f of fields) {
			expect(f).not.toMatch(/type="number"/);
			expect(f).toMatch(/inputmode="decimal"/);
		}
	});

	it("routes the numpad to whichever quantity the operator tapped", () => {
		expect(board).toMatch(/numTarget/);
	});
});

// Finishing the planned remainder is the most common thing an operator does at
// the end of a shift, and it is a four-digit number typed with a gloved finger.
// The source design puts a "Всё" key in the pad for exactly this and captions it
// "остаток по заказу: 1 360 · нажмите «Всё»".
describe("the fill key", () => {
	it("offers one tap for the whole remaining balance", () => {
		expect(pad).toMatch(/props\.fill/);
		expect(board).toMatch(/<NumPad[^>]*:fill=/s);
	});

	// It REPLACES the buffer. Routed through applyNumpadKey it would concatenate,
	// so a half-typed "500" plus the balance would post 5001360.
	it("replaces what was typed instead of appending to it", () => {
		const fillHandler = pad.match(/function fill[\s\S]{0,200}?\n}/) || [""];
		expect(pad).toMatch(/sanitizeNumeric\(/);
		expect(fillHandler[0]).not.toMatch(/applyNumpadKey/);
	});

	// A key that does nothing teaches operators to distrust the whole pad, and
	// the pad itself cannot know a balance — the caller supplies it or there is
	// no key.
	it("does not render a dead key when there is nothing to fill", () => {
		expect(pad).toMatch(/v-if="fill"/);
	});

	// "All of it was scrap" is not a sensible one-tap default; offering it there
	// invites a mis-tap that writes off a whole order.
	it("is offered for good output only, never for scrap", () => {
		// Scoped to the <NumPad> tag, not to the file. The bare substring
		// "numTarget === 'produced'" also appears in the field's :class binding
		// above, so a file-wide match stays green with the fill key wired to the
		// scrap box or with :fill deleted outright.
		const tag = board.match(/<NumPad[\s\S]*?\/>/);
		expect(tag, "the pad should be mounted").toBeTruthy();
		const fill = tag[0].match(/:fill="([^"]*)"/);
		expect(fill, "the pad should be handed a balance to fill").toBeTruthy();
		expect(fill[1]).toMatch(/numTarget === 'produced'/);
		// …and the other branch hands it nothing, which is what suppresses the key.
		expect(fill[1]).toMatch(/:\s*''/);
	});
});
