import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../components/Typeahead.vue"), "utf8");

/**
 * Review follow-up (P3, H): the `placeholder` prop defaulted to the bare
 * English literal "Search…" instead of routing through t(), so any caller
 * that left it unset showed English on the ru/uz/uzc/tr locales. "Search…"
 * (no "⌘K" suffix) already ships a non-empty target in all five catalogues
 * (stabler/translations/{en,ru,uz,uzc,tr}.csv) — only the component was
 * skipping it.
 */
describe("Typeahead's default placeholder is translated (review follow-up, P3)", () => {
	it("does not default the placeholder prop to a bare English literal", () => {
		expect(src).not.toContain('default: "Search…"');
	});

	it("imports t() from the shared i18n composable", () => {
		expect(src).toContain('import { t } from "../composables/i18n.js"');
	});

	it("falls back to the translated 'Search…' when no placeholder is given", () => {
		expect(src).toMatch(/placeholder\s*\|\|\s*t\(["']Search…["']\)/);
	});
});
