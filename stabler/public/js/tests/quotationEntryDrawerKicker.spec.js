import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../components/QuotationEntryDrawer.vue"), "utf8");

/**
 * The drawer's kicker line was `{{ deal }}{{ dealLabel ? \` · ${dealLabel}\` : "" }}`
 * — it always appends the label whenever one is truthy, with no check that the
 * label actually says something the deal id does not.
 *
 * SourcingWorkspace.vue's `dealLabel` ref defaults to `route.query.deal_label
 * || route.query.deal` (SourcingWorkspace.vue:34) and NOTHING in this codebase
 * ever sets a `deal_label` query param when navigating here (checked: router.js,
 * useTenderContext.js's CONTEXT_QUERY_KEYS, BidPricing.vue, RfqDetail.vue,
 * RfqList.vue) — so on every ordinary link-in, `dealLabel` starts out equal to
 * `deal` itself. `tender_quotations` (the workspace's own data call) returns no
 * organization/label field either, so the workspace has nothing better to pass
 * in that case; `:deal-label="dealLabel"` (SourcingWorkspace.vue) already hands
 * the drawer the best label it has. The kicker printing it unconditionally is
 * what produced "CRM-DEAL-2026-00015 · CRM-DEAL-2026-00015" — measured
 * 2026-09-05 RU walk, docs/uat/tender/2026-09-05-mikas-gercek-deneme-senaryosu.md
 * §G (finding 2).
 *
 * `kickerLabel` is the pure expression pulled out of the template: given the
 * deal id and whatever label the caller passed, what (if anything) should
 * follow it. Executed, not grepped.
 */
function braceMatched(from) {
	let depth = 0;
	for (let i = from; i < src.length; i++) {
		if (src[i] === "{") depth++;
		else if (src[i] === "}" && --depth === 0) return src.slice(from, i + 1);
	}
	throw new Error("unterminated block");
}

function extractFunction(name) {
	const at = src.indexOf(`function ${name}(`);
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	const braceStart = src.indexOf("{", at);
	return src.slice(at, braceStart) + braceMatched(braceStart);
}

function build() {
	const factory = new Function(`${extractFunction("kickerLabel")}\nreturn kickerLabel;`);
	return factory();
}

describe("QuotationEntryDrawer's kicker label (kickerLabel)", () => {
	const kickerLabel = build();

	it("omits the label when it is the same string as the deal id", () => {
		// This is the exact defect: the workspace had nothing better than the deal
		// id to pass as a label, and the kicker printed it twice.
		expect(kickerLabel("CRM-DEAL-2026-00015", "CRM-DEAL-2026-00015")).toBe("");
	});

	it("shows the label, separated, when it genuinely differs from the deal id", () => {
		expect(kickerLabel("CRM-DEAL-2026-00015", "Mikas LLC")).toBe(" · Mikas LLC");
	});

	it("omits the label when the caller passed none", () => {
		expect(kickerLabel("CRM-DEAL-2026-00015", "")).toBe("");
		expect(kickerLabel("CRM-DEAL-2026-00015", undefined)).toBe("");
	});
});

describe("the kicker template calls kickerLabel instead of inlining the old ternary", () => {
	it("no longer prints dealLabel unconditionally", () => {
		// WHAT WOULD MAKE THIS FAIL: reverting to
		// `{{ dealLabel ? \` · ${dealLabel}\` : "" }}` in the header markup — the
		// exact shape that cannot tell "no better label" from "a real one".
		const kickerAt = src.indexOf("ds-drawer-kicker");
		expect(kickerAt, "ds-drawer-kicker is gone").toBeGreaterThan(-1);
		const line = src.slice(kickerAt, src.indexOf("</div>", kickerAt));
		expect(line).toMatch(/kickerLabel\(\s*deal\s*,\s*dealLabel\s*\)/);
	});
});
