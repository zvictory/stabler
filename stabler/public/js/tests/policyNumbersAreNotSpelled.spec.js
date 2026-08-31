import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "fs";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const tenderPages = resolve(here, "../pages/tender");

/**
 * The procurement threshold is one number, served by the backend
 * (`api/_procurement_policy.py`, reaching the SPA on `tender_views().policy`).
 *
 * A screen that prints its own copy is the half of the drift that the user
 * actually reads. The server can be corrected in one place and every badge on
 * these pages will still say "5" — which is worse than the old inconsistency,
 * because the numbers now disagree with an enforcement rule that has genuinely
 * moved.
 *
 * Two shapes are caught, because the number appears in both: a binding printed
 * next to a counter (`{{ data.count }} / 5`), and a translated sentence that
 * spells it (`"at least 5 quotations from 2 countries"`).
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

/**
 * `{{ data.count }} / 5`, `sq_count }}/5`, `quotation_count >= 5`.
 *
 * Zero is excluded deliberately: `c.sq_count > 0` asks whether ANY quotation
 * has arrived, which is an emptiness check and stays correct whatever the
 * policy is. Only a positive literal is a copy of the threshold.
 */
const COUNTER_AGAINST_A_NUMBER = /(?:sq_count|quotation_count|\.count|countries)\s*\}*\s*[/<>=]+\s*[1-9]\d*/g;

/** `5 quotes`, `2 countries`, `5-quote`, `at least 5 quotations` */
const A_SENTENCE_THAT_SPELLS_IT = /\d+[-\s]?(?:quote|countr)/gi;

const files = vueFilesUnder(tenderPages);

describe("tender screens do not spell the procurement threshold", () => {
	it("scans a non-empty set of pages", () => {
		expect(files.length).toBeGreaterThan(0);
	});

	for (const path of files) {
		const short = path.slice(tenderPages.length + 1);
		const src = readFileSync(path, "utf8");
		it(`${short} prints no threshold of its own`, () => {
			const hits = [
				...(src.match(COUNTER_AGAINST_A_NUMBER) || []),
				...(src.match(A_SENTENCE_THAT_SPELLS_IT) || []),
			];
			expect(
				hits,
				`${short} carries its own copy of the policy number. Read it from the ` +
					"session store (tender_views().policy) so one server-side change moves " +
					"every screen.",
			).toEqual([]);
		});
	}
});
