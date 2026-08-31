import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "fs";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const pagesRoot = resolve(here, "../pages");

/**
 * A tab bar that changes the URL and nothing else is worse than no tab bar:
 * the highlight moves, so the user believes the click landed, and then reads
 * the previous screen as the new one's content.
 *
 * `TenderWorkspaceTabs.selectTab()` does exactly one thing —
 * `router.replace({ query: { ...route.query, tab } })`. It emits nothing and
 * navigates nowhere. So the component is only honest on a page that reads
 * `route.query.tab` back and renders from it; on any other page its four
 * destinations are decoration.
 *
 * This asserts the contract rather than the file list, so it keeps holding
 * when a third page mounts the component — which is the moment the mistake
 * is cheapest to catch and likeliest to be repeated.
 */
function vueFilesUnder(dir) {
	const out = [];
	for (const entry of readdirSync(dir, { withFileTypes: true })) {
		const full = join(dir, entry.name);
		if (entry.isDirectory()) out.push(...vueFilesUnder(full));
		else if (entry.name.endsWith(".vue")) out.push(full);
	}
	return out;
}

const COMPONENT = "TenderWorkspaceTabs";

const mounts = vueFilesUnder(pagesRoot)
	.map((path) => ({ path, src: readFileSync(path, "utf8") }))
	.filter(({ path, src }) => !path.endsWith(`${COMPONENT}.vue`) && src.includes(`<${COMPONENT}`));

describe("every page that shows the workspace tab bar acts on the tab", () => {
	it("finds at least one page mounting it — otherwise this spec proves nothing", () => {
		expect(mounts.length).toBeGreaterThan(0);
	});

	for (const { path, src } of mounts) {
		const shortPath = path.slice(pagesRoot.length + 1);
		it(`${shortPath} reads route.query.tab back`, () => {
			expect(
				src.includes("route.query.tab"),
				`${shortPath} renders ${COMPONENT} but never reads route.query.tab — ` +
					"clicking a tab there moves the highlight and changes nothing else. " +
					"Either render from the tab, or stop showing the bar on this page.",
			).toBe(true);
		});
	}
});
