import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../components/Typeahead.vue"), "utf8");

/**
 * Same defect class as the `placeholder` prop (typeaheadPlaceholder.spec.js):
 * `noResultsText` defaulted to the bare English literal "No matches found", so
 * every caller that left it unset showed English on ru/uz/uzc/tr the moment a
 * search came back empty. "No matches found" already ships a non-empty target
 * in all five catalogues (stabler/translations/{en,ru,uz,uzc,tr}.csv, checked
 * 2026-09-06) -- only the component skipped it. The default becomes "" and the
 * template falls back through t(), the shape the placeholder fix settled on,
 * so a caller-supplied text still wins and the fallback is the translated one.
 */
describe("Typeahead's default empty-state text is translated", () => {
	it("does not default noResultsText to a bare English literal", () => {
		expect(src).not.toContain('default: "No matches found"');
	});

	it("imports t() from the shared i18n composable", () => {
		expect(src).toContain('import { t } from "../composables/i18n.js"');
	});

	it("falls back to the translated 'No matches found' when no text is given", () => {
		expect(src).toMatch(/noResultsText\s*\|\|\s*t\(["']No matches found["']\)/);
	});
});
