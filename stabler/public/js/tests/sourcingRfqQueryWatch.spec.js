import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/SourcingWorkspace.vue"), "utf8");

/**
 * The `?rfq=` deep link is supposed to pre-select an RFQ in the "Add
 * quotation" drawer. `onMounted` read `route.query.rfq` exactly once
 * (SourcingWorkspace.vue), so the drawer only opened when the workspace was
 * freshly *mounted* — arriving from another route. A query-only change on
 * the SAME route (e.g. a shared `?deal=…&rfq=…` link opened while the
 * workspace is already on screen) does not recreate the component, so
 * `onMounted` never re-ran and the drawer stayed shut.
 *
 * Measured 2026-09-05 RU walk (docs/uat/tender/2026-09-05-mikas-gercek-deneme-senaryosu.md
 * §G.5): "`?rfq=` aynı rotada çekmeceyi açmaz... RFQ detayından gelince
 * çalışır (rota değişir)" — works only when the route itself changes.
 *
 * `rfqNameFromQuery` is the pure decision pulled out of the watcher: given
 * whatever `route.query.rfq` currently is, which RFQ (if any) should be
 * pre-selected. Executed, not grepped — same shape as
 * sourcingAddQuotationEvent.spec.js.
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

/** The `(...)` starting at `from` (which must be an opening paren), parens balanced. */
function parenMatched(from) {
	let depth = 0;
	for (let i = from; i < src.length; i++) {
		if (src[i] === "(") depth++;
		else if (src[i] === ")" && --depth === 0) return src.slice(from, i + 1);
	}
	throw new Error("unterminated call");
}

function build() {
	const factory = new Function(`${extractFunction("rfqNameFromQuery")}\nreturn rfqNameFromQuery;`);
	return factory();
}

describe("SourcingWorkspace's ?rfq= deep-link decision (rfqNameFromQuery)", () => {
	const rfqNameFromQuery = build();

	it("names the RFQ to pre-select when the query carries one", () => {
		expect(rfqNameFromQuery("PUR-RFQ-2026-00003")).toBe("PUR-RFQ-2026-00003");
	});

	it("is nothing to do when the query has no rfq", () => {
		expect(rfqNameFromQuery(undefined)).toBe("");
		expect(rfqNameFromQuery("")).toBe("");
	});
});

describe("the ?rfq= deep link is wired to react to every change, not just first mount", () => {
	// WHAT WOULD MAKE THIS FAIL: reverting to reading route.query.rfq only
	// inside onMounted — the exact shape that cannot react to a query-only
	// change on the same route, which is what the RU walk measured as broken.
	it("watches route.query.rfq with immediate:true, so it also covers first mount", () => {
		const arrowAt = src.indexOf("() => route.query?.rfq");
		expect(arrowAt, "no watch() targets route.query.rfq").toBeGreaterThan(-1);
		const watchCallAt = src.lastIndexOf("watch(", arrowAt);
		const watchBlock = parenMatched(watchCallAt + "watch".length);
		expect(watchBlock).toMatch(/immediate:\s*true/);
		expect(watchBlock).toMatch(/openAddQuotation/);
		expect(watchBlock).toMatch(/router\.replace/);
	});

	it("no longer decides this in onMounted — one code path, so it cannot double-open", () => {
		const mountedAt = src.indexOf("onMounted(() => {");
		expect(mountedAt, "onMounted is gone").toBeGreaterThan(-1);
		const mountedBlock = src.slice(mountedAt, src.indexOf("});", mountedAt) + 3);
		expect(
			mountedBlock,
			"onMounted still reads route.query.rfq directly — that is the pre-fix shape " +
				"and reintroduces the risk of opening the drawer twice for one query value"
		).not.toMatch(/route\.query\??\.rfq/);
	});
});
