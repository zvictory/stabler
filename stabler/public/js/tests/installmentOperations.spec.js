import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const opsPath = resolve(here, "../pages/installment/Operations.vue");
const src = readFileSync(opsPath, "utf8");

/**
 * Extract a `const <name> = computed(() => { ... })` body from the SFC and turn
 * it into a callable function.
 *
 * Mounting the page would be the direct way to assert this, but @vue/test-utils
 * is not a devDependency of this repo (measured 2026-08-16 against package.json)
 * and adding one is not this change's business. Executing the shipped source is
 * the next best thing, and it is strictly better than asserting on source text:
 * a `toContain(".sort(")` check passes for a sort that sorts the wrong way.
 */
function callComputed(name, { summary, user }) {
	const marker = `const ${name} = computed(() => {`;
	const start = src.indexOf(marker);
	expect(start, `${name} not found in Operations.vue`).toBeGreaterThan(-1);
	const bodyStart = start + marker.length;
	const end = src.indexOf("\n});", bodyStart);
	expect(end, `${name} has no closing '});'`).toBeGreaterThan(bodyStart);
	const body = src.slice(bodyStart, end);
	// The body's only free names. formatMoney is stubbed so the assertion is
	// about ordering, not about locale formatting (money.spec.js owns that).
	const fn = new Function(
		"summary",
		"user",
		"formatMoney",
		body
	); /* eslint-disable-line no-new-func */
	return fn(summary, user, (amt, curr) => `${curr} ${amt}`);
}

const USER = { value: { language: "en" } };

describe("Operations.vue — shared SPA foundations (stabler-k3wk)", () => {
	it("renders its scorecards with the shared KpiCard, not hand-rolled markup", () => {
		// The design brief's rule is 'reuse before creating'. The page previously
		// hand-rolled four score cards; the only `card card-sm` blocks left are the
		// loading skeleton and the clickable queue tiles (the latter tracked
		// separately — KpiCard's `lines` prop cannot carry both a count and a
		// currency breakdown, which is a design call, not a mechanical swap).
		expect(src).toContain('import KpiCard from "../../components/KpiCard.vue";');
		expect(src).not.toContain('<div class="subheader">{{ curr }}</div>');
		expect(src).not.toContain('{{ t("Total Agreements") }}</div>');
	});
});

describe("Operations.vue — overdue outstanding ordering", () => {
	// This is the one behaviour the KpiCard retrofit changed, and it is the
	// reason the sort exists: KpiCard promotes lines[0] to the big hero value and
	// demotes the rest to small grey rows. The old markup looped the object and
	// rendered every currency at the same weight, so order was cosmetic. It is
	// not cosmetic any more — drop the sort and whichever currency the API
	// happened to serialise first becomes the headline overdue figure, rendered
	// large and in red. A 400 USD exposure would outrank a 900,000,000 UZS one.
	it("puts the largest exposure first, whatever order the payload arrived in", () => {
		const lines = callComputed("overdueOutstandingLines", {
			summary: {
				value: {
					overdue_outstanding_by_currency: { USD: 400, UZS: 900_000_000, EUR: 12_000 },
				},
			},
			user: USER,
		});
		expect(lines).toEqual(["UZS 900000000", "EUR 12000", "USD 400"]);
	});

	it("is empty when nothing is overdue, so the card can be hidden entirely", () => {
		// The template's v-if reads this length. Returning a one-element array of
		// zeroes here would render an 'Overdue Outstanding: 0' card on a portfolio
		// with no overdue money at all.
		for (const payload of [{}, { overdue_outstanding_by_currency: {} }]) {
			expect(callComputed("overdueOutstandingLines", { summary: { value: payload }, user: USER })).toEqual([]);
		}
		// And when the summary has not loaded yet.
		expect(callComputed("overdueOutstandingLines", { summary: { value: null }, user: USER })).toEqual([]);
	});
});
