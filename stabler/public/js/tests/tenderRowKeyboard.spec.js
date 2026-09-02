import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(resolve(here, "..", rel), "utf8");

/**
 * A table row that opens a record must be reachable and operable without a
 * mouse. Acceptance rows P12 (prompt 14, director board) and M13 (prompt 17,
 * my tenders): both were bare `<tr @click>` — no tab stop, no key handler, and
 * on my tenders an inline `cursor:pointer` as the only hint that the row does
 * anything at all.
 *
 * Measured 2026-09-02: eleven `role="button"` sites across the SPA, and the
 * only one that is actually reachable is TenderFunnel's funnel row
 * (`role="button" tabindex="0" @keydown.enter`). The `<tr role="button">` sites
 * declare a button and give it no tab stop, which announces a control that
 * cannot be focused. These two rows follow the funnel, not the majority — and
 * go one further: a declared button answers Space as well as Enter, so
 * declaring the role and handling only Enter is the same defect as painting a
 * span to look like a button (prompt 13, D17).
 *
 * DOM-less, per vitest.config.mjs (`environment: "node"`).
 */

const ROWS = [
	{
		prompt: 14,
		row: "P12",
		file: "pages/tender/DirectorBoard.vue",
		marker: 'class="board-row"',
		handler: "openDeal(r.deal)",
		// The manager <select> lives in the last cell of this row.
		guarded: true,
	},
	{
		prompt: 17,
		row: "M13",
		file: "pages/tender/MyTenders.vue",
		marker: 'v-for="r in filteredRows"',
		handler: "openDeal(r.deal)",
		guarded: false,
	},
];

/** The opening `<tr ...>` tag containing `marker`. */
function rowTag(file, marker) {
	const src = read(file);
	const at = src.indexOf(marker);
	expect(at, `${file}: marker ${marker} not found — has the row moved?`).toBeGreaterThan(-1);
	const open = src.lastIndexOf("<tr", at);
	return src.slice(open, src.indexOf(">", at) + 1);
}

for (const { prompt, row, file, marker, handler, guarded } of ROWS) {
	describe(`${prompt} · ${row} · ${file.split("/").pop()}`, () => {
		const tag = () => rowTag(file, marker);

		it("is a tab stop", () => {
			// WHAT WOULD MAKE THIS FAIL: dropping tabindex. Without it the row
			// cannot be focused, so no key handler on it can ever fire and the only
			// way to open a tender is a pointer. This is the whole defect: both rows
			// opened records and neither could be reached.
			expect(tag()).toMatch(/tabindex="0"/);
		});

		it("says what it is", () => {
			// WHAT WOULD MAKE THIS FAIL: removing role="button". A focusable <tr>
			// with a click handler and no role is announced as a table row, so a
			// screen-reader user reaches it and is told nothing happens there.
			expect(tag()).toMatch(/role="button"/);
		});

		it("opens on Enter, through the same handler as the click", () => {
			// WHAT WOULD MAKE THIS FAIL: wiring the key handler to a different
			// function than the click. Two paths into one action drift; the point of
			// asserting the handler text is that the keyboard opens the SAME record
			// the pointer does.
			const t = tag();
			expect(t).toMatch(/@keydown\.enter[.\w]*="/);
			expect(t.match(new RegExp(handler.replace(/[.()]/g, "\\$&"), "g"))?.length ?? 0).toBeGreaterThanOrEqual(2);
		});

		it("opens on Space too, and does not scroll the page doing it", () => {
			// WHAT WOULD MAKE THIS FAIL: handling only Enter, which is what the one
			// working precedent in the SPA does (TenderFunnel). role="button" is a
			// promise: assistive tech tells the user this is a button, and a button
			// answers Space. Without .prevent, Space scrolls the page instead —
			// so the row would both fail to open and move the table out of view.
			const t = tag();
			expect(t).toMatch(/@keydown\.space[.\w]*="/);
			expect(t).toMatch(/@keydown\.space[.\w]*\bprevent\b/);
		});

		if (guarded) {
			it("does not fire from a control inside the row", () => {
				// WHAT WOULD MAKE THIS FAIL: an unguarded @keydown. This row's last
				// cell holds the manager <select>; keying Enter there would bubble to
				// the row and navigate away from the assignment the user was making.
				// `.self` restricts the handler to the row's own focus.
				const t = tag();
				expect(t).toMatch(/@keydown\.enter[.\w]*\bself\b/);
				expect(t).toMatch(/@keydown\.space[.\w]*\bself\b/);
			});
		}
	});
}

describe("the elements that still only claim to be buttons", () => {
	it("is a known, counted set — not a sweep this change performed", () => {
		// WHAT WOULD MAKE THIS FAIL: the count moving. Measured 2026-09-02 across
		// the SPA: eleven role="button" elements, eight of them with no tab stop.
		// They declare a control assistive tech will announce and then cannot be
		// reached, which is the same defect these two rows had. They are NOT this
		// change's scope — .claude/rules/10-frontend.md: correct one when you next
		// edit that file for another reason, this is not a sweep. Pinning the number
		// means a NEW unreachable role="button" fails here instead of passing
		// silently, and fixing one of the eight fails here too, which is the cheap
		// prompt to update the count rather than the sweep itself.
		//
		// An <a> counts unless it has an href: the one in service/Dashboard.vue
		// carries a @click and no href, so the browser gives it no tab stop either.
		const src = readdirVue();
		const unreachable = src.flatMap(({ file, text }) =>
			(text.match(/<[A-Za-z][^>]*role="button"[^>]*>/gs) ?? [])
				.filter((tag) => !/tabindex=/.test(tag))
				.filter((tag) => !(/^<a[ >]/.test(tag) && /\bhref=/.test(tag)))
				.map(() => file),
		);
		expect(unreachable.length, `unreachable role="button" sites: ${[...new Set(unreachable)].join(", ")}`).toBe(8);
	});
});

/** Every .vue file under public/js, as {file, text}. */
function readdirVue() {
	const root = resolve(here, "..");
	const out = [];
	const walk = (dir) => {
		for (const entry of readdirSync(dir, { withFileTypes: true })) {
			const full = resolve(dir, entry.name);
			if (entry.isDirectory()) walk(full);
			else if (entry.name.endsWith(".vue")) out.push({ file: entry.name, text: readFileSync(full, "utf8") });
		}
	};
	walk(root);
	return out;
}
