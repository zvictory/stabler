import { describe, expect, it } from "vitest";

import { t, tlang } from "../composables/i18n.js";

// The translation fixture these assertions read lives in tests/setup.js -- it has
// to be installed on `window` before this module is first imported, because
// i18n.js captures the table at module load.

describe("t — lookup", () => {
	it("returns the translation when the key is known", () => {
		expect(t("Draft")).toBe("Черновик");
	});

	// The whole point of falling back to the source string: the five CSVs are
	// never all complete at once, and a missing Uzbek row must render readable
	// English, not an empty cell or the literal key.
	it("falls back to the source string for an unknown key", () => {
		expect(t("Some string nobody has translated yet")).toBe(
			"Some string nobody has translated yet"
		);
	});

	it("returns the source string unchanged when there are no params", () => {
		expect(t("Dashboard")).toBe("Dashboard");
	});
});

describe("t — placeholders", () => {
	// {name} syntax matches Frappe's __(), which is what lets keys be lifted from
	// the existing CSVs verbatim instead of being re-authored for the SPA.
	it("substitutes a named placeholder inside the translated string", () => {
		expect(t("Hello {name}", { name: "Daisy" })).toBe("Привет, Daisy");
	});

	it("substitutes into the fallback string too", () => {
		expect(t("Untranslated {thing}", { thing: "row" })).toBe("Untranslated row");
	});

	// replaceAll, not replace: a plural string like "{n} of {n}" must fill both.
	it("replaces every occurrence, not just the first", () => {
		expect(t("{n} of {n}", { n: 3 })).toBe("3 из 3");
	});

	it("coerces non-string params", () => {
		expect(t("Untranslated {thing}", { thing: 0 })).toBe("Untranslated 0");
	});

	it("leaves a placeholder alone when no value is supplied for it", () => {
		expect(t("Hello {name}", { other: "x" })).toBe("Привет, {name}");
	});
});

describe("tlang", () => {
	it("reports the boot language", () => {
		expect(tlang()).toBe("ru");
	});
});
