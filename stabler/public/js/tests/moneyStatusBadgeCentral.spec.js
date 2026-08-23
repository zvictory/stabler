import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const SCREENS = {
	Expenses: readFileSync(resolve(here, "../pages/money/Expenses.vue"), "utf8"),
	Transfers: readFileSync(resolve(here, "../pages/money/Transfers.vue"), "utf8"),
};

/**
 * Both money screens kept a private docstatus->colour map beside the shared one.
 *
 * StatusBadge.vue's own contract says per-page status maps are FORBIDDEN, and
 * the copy proved why: it emitted its labels as bare string literals, never
 * through `t()`. A Russian or Uzbek session read "Draft"/"Submitted"/"Cancelled"
 * in English on every row of the list and on the detail card -- the two places a
 * user looks to answer "did this hit the ledger yet?". The colours agreed with
 * `STATUS_MAP.docstatus` by luck, not by construction; nothing kept them in step.
 *
 * The line the tests draw is deliberately at the colour literal rather than at
 * the function name: a map is a map whatever it is called, and a badge colour
 * chosen inside a page is the defect regardless of how it is spelled.
 */
describe.each(Object.entries(SCREENS))("%s — status colours come from status.js", (label, src) => {
	const script = src.slice(0, src.indexOf("</script>"));

	it("picks no badge colour of its own", () => {
		expect(script, `${label}: a badge colour is chosen in the page`).not.toMatch(
			/bg-[a-z]+-lt/
		);
	});

	// The user-visible half: an untranslated docstatus label.
	it("spells no docstatus label as a bare literal", () => {
		expect(script).not.toMatch(/["'](Draft|Submitted|Cancelled)["']/);
	});

	it("renders the list row's status through StatusBadge", () => {
		expect(src).toMatch(/<StatusBadge[^>]*:docstatus="r\.docstatus"/);
	});

	it("renders the detail card's status through StatusBadge", () => {
		expect(src).toMatch(/<StatusBadge[^>]*:docstatus="detail\.docstatus"/);
	});

	// The header badge (added when the row click stopped opening the editor) and
	// the datagrid's "Status" item said the same thing four lines apart. Two
	// badges for one fact is not twice as clear; the labelled row goes, the
	// badge beside the title stays, because that is where the Amend button is.
	it("states the status once in the detail card", () => {
		expect(src).not.toMatch(/datagrid-title">\{\{ t\("Status"\) \}\}/);
	});
});
