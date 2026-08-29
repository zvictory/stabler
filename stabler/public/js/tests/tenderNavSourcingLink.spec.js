import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/TenderNav.vue"), "utf8");

/**
 * docs/backlog.md:326 — "Kalan: deploy onayi + TenderNav sourcing linki."
 * `/tender/sourcing` (router.js:297) is reachable today only from callers that
 * already carry a `deal` (RfqList, RfqDetail, crm/Deals, purchasing/Suppliers).
 * SourcingWorkspace.vue has its own deal picker and a real empty state
 * ("Pick a tender deal to view its sourcing workspace") when no `deal` is in
 * the query, so a top-bar link is safe: it does not need a caller to hand it
 * a deal.
 *
 * The v-if is EXECUTED, not grepped — a `toContain('can(\'sourcing\')')`
 * assertion passes just as happily if the gate were pasted onto the wrong
 * link or swapped for `can('director')`, which is exactly the kind of
 * backwards-wiring manufacturingTabGates.spec.js exists to catch on the
 * manufacturing tab bar.
 */
function extractRouterLinkTag(routePath) {
	const marker = `to="${routePath}"`;
	const at = src.indexOf(marker);
	expect(at, `no router-link to ${routePath} — has the link moved or not been added?`).toBeGreaterThan(-1);
	const tagStart = src.lastIndexOf("<router-link", at);
	const tagEnd = src.indexOf(">", at);
	return src.slice(tagStart, tagEnd + 1);
}

function vIfExpression(tag) {
	const m = tag.match(/v-if="([^"]+)"/);
	expect(m, "this router-link has no v-if gate at all").not.toBeNull();
	return m[1];
}

function evalGate(expr, can) {
	const factory = new Function("can", `return (${expr});`);
	return factory(can);
}

describe("TenderNav links to the sourcing workspace, gated like RFQs", () => {
	const tag = extractRouterLinkTag("/tender/sourcing");
	const expr = vIfExpression(tag);

	it("is visible to a user with the sourcing tender view", () => {
		expect(evalGate(expr, (v) => v === "sourcing")).toBe(true);
	});

	it("is hidden from a user without the sourcing view (e.g. declarant-only)", () => {
		expect(evalGate(expr, (v) => v === "declarant")).toBe(false);
	});

	it("is gated the same way as the neighbouring RFQs link", () => {
		const rfqTag = extractRouterLinkTag("/tender/rfq");
		expect(vIfExpression(rfqTag)).toBe(expr);
	});
});
