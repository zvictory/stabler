import { describe, expect, it } from "vitest";

import { SAVE_MODES, resolveSaveMode } from "../composables/saveMode.js";

describe("the remembered save mode can only ever be a mode that saves", () => {
	// The defect this pins: the Expense form's split button offered a third
	// item, "Save & clear", whose handler wrote the choice to localStorage and
	// then reset the form WITHOUT calling the API. Because the choice persists,
	// the big primary button afterwards read "Save & clear" and discarded — six
	// typed expense lines, no dialog, no toast, no undo. The item is now a
	// plainly labelled "Clear form" and is not a save mode, but the string is
	// already sitting in the localStorage of everyone who ever picked it.
	it("refuses a stored 'clear' — the primary button must never discard", () => {
		expect(resolveSaveMode("clear")).toBe("close");
	});

	it("keeps a mode the user actually chose", () => {
		expect(resolveSaveMode("new")).toBe("new");
		expect(resolveSaveMode("close")).toBe("close");
	});

	it("falls back to closing when nothing readable is stored", () => {
		expect(resolveSaveMode(null)).toBe("close");
		expect(resolveSaveMode("")).toBe("close");
		expect(resolveSaveMode("Save & clear")).toBe("close");
	});

	// The label map and the mode set are read from the same place, so a mode
	// can never exist without a label — that mismatch is what let a button say
	// one thing and do another.
	it("offers exactly the modes that have a label", () => {
		expect(SAVE_MODES).toEqual(["close", "new"]);
	});
});
