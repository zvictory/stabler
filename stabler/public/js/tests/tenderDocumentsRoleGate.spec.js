import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/TenderDocuments.vue"), "utf8");
const py = readFileSync(resolve(here, "../../../api/_tender_documents.py"), "utf8");

/**
 * Who the document centre lets attach a file, and whether it says so first.
 *
 * Four roles share this one screen — declarant, logist, sourcing, director —
 * and the row itself carries the `role` that decides who may write it. The
 * server has always enforced that (`_require_doc_role_write`, keyed on
 * DOC_ROLE_WRITER_VIEWS). The screen showed no role column at all, and rendered
 * "Upload file" and "Waive" enabled on every row regardless.
 *
 * So a logist opened the modal for a customs row, typed a file name and a
 * server path by hand, submitted, and learned they were refused by a red toast.
 * The refusal was always going to happen; the only question was whether they
 * found out before or after doing the work.
 *
 * The interesting failure mode is not the gate — it is the gate DRIFTING. A
 * client that keeps its own copy of the rule and gets it wrong produces the
 * exact bug being fixed, in reverse: a button that looks disabled the server
 * would have allowed, or an enabled one it refuses. So the map is not asserted
 * against a hard-coded literal here. It is read out of the Python and executed
 * against the JavaScript, role by role and view by view — if either side moves,
 * this fails.
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

const canWrite = new Function(`${extractFunction("canWrite")}\nreturn canWrite;`)();

/** The server's own map, read out of the Python rather than restated here. */
function serverMap() {
	const at = py.indexOf("DOC_ROLE_WRITER_VIEWS = {");
	expect(at, "the server's writer map is gone — has it been renamed?").toBeGreaterThan(-1);
	const body = py.slice(at, py.indexOf("}", at));
	const map = {};
	for (const [, role, views] of body.matchAll(/"(\w+)":\s*\(([^)]*)\)/g)) {
		map[role] = [...views.matchAll(/"(\w+)"/g)].map((m) => m[1]);
	}
	expect(Object.keys(map).length, "parsed no roles out of the Python").toBeGreaterThan(0);
	return map;
}

describe("the document centre agrees with the server about who may write", () => {
	const server = serverMap();

	it("lets exactly the views the server lets, for every role it defines", () => {
		for (const [role, views] of Object.entries(server)) {
			for (const view of views) {
				expect(canWrite({ role }, [view]), `${role} should be writable by ${view}`).toBe(true);
			}
		}
	});

	it("refuses every view the server does not list, for every role", () => {
		const all = [...new Set(Object.values(server).flat())];
		for (const [role, views] of Object.entries(server)) {
			for (const view of all.filter((v) => !views.includes(v))) {
				expect(canWrite({ role }, [view]), `${role} must not be writable by ${view}`).toBe(false);
			}
		}
	});

	it("treats a row with no role, or an unknown one, the way the server does", () => {
		// `_require_doc_role_write` falls back to the "general" entry rather than
		// refusing outright, so a row written by an older version stays workable.
		const general = server.general;
		expect(canWrite({}, general)).toBe(true);
		expect(canWrite({ role: "" }, general)).toBe(true);
		expect(canWrite({ role: "not_a_role" }, general)).toBe(true);
	});

	it("refuses when the user holds no tender views at all", () => {
		// Views arrive asynchronously. Until they do the honest answer is no —
		// offering a control that will be refused is the whole defect.
		expect(canWrite({ role: "customs" }, [])).toBe(false);
	});
});

describe("the screen shows the role and stops offering what it will refuse", () => {
	it("names the responsible role in the read view", () => {
		// Anchored on the READ view's own table — the editor above it has said
		// "Responsible role" all along, which is exactly why the reader could
		// not see it: the column existed only for whoever was editing the list.
		const at = src.indexOf("Attached files / Waiver");
		expect(at, "the read view's file column is gone").toBeGreaterThan(-1);
		const head = src.slice(src.lastIndexOf("<thead>", at), src.indexOf("</thead>", at));
		expect(head).toMatch(/Responsible role/);
	});

	it("gates both write actions on the same answer", () => {
		expect((src.match(/:disabled="!canWrite\(/g) || []).length).toBeGreaterThanOrEqual(2);
	});

	it("asks the session for the views it is gating on", () => {
		// Without this the array stays empty and every row reads as forbidden.
		expect(src).toMatch(/ensureTenderViews\(\)/);
	});
});

describe("a file attached here can be detached here", () => {
	it("calls the removal endpoint the sister panel already uses", () => {
		// Until now the only route to removing a wrong file was a different
		// screen entirely — the PO board's documents panel.
		expect(src).toMatch(/tender_documents\.remove_tender_document/);
	});

	it("removes one named file, not 'the latest'", () => {
		// This screen lists every attachment with its own name and date, so the
		// control has to say which one it is removing.
		const at = src.indexOf("remove_tender_document");
		expect(src.slice(at, at + 300)).toMatch(/file_url/);
	});
});
