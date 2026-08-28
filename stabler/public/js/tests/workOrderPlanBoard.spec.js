import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/manufacturing/WorkOrderPlan.vue"), "utf8");

/**
 * The planning board's two client-side refusals.
 *
 * Both exist because of one measurement on anjan, 2026-08-28:
 * `wip_warehouse`.allow_on_submit is 0 while `planned_start_date`.allow_on_submit
 * is 1. So an order moves between days and never between lines — and a board
 * that offered the cross-line drag would have failed on the gesture its own
 * layout invites most, after the planner had already made it.
 *
 * The backend refuses both cases too (`test_wo_role_scoping_integration`
 * proves that against the live database). What is pinned here is that the
 * screen refuses *before* the call, because the version that lets you drop an
 * order on another line and then shows a red box is the one that teaches a
 * planner the board is unreliable.
 *
 * Same constraint as finishSweepGuard.spec.js — @vue/test-utils is not a
 * devDependency, so the component is not mounted. The guards are pulled out of
 * the shipped SFC and EXECUTED. A toContain() assertion passes just as happily
 * on a guard wired backwards, and "wired backwards" here means the board
 * silently allows exactly the move ERPNext will not write.
 */
function fnSource(name) {
	const start = src.indexOf(`function ${name}(`);
	expect(start, `${name}() is not in the shipped component`).toBeGreaterThan(-1);
	const end = src.indexOf("\n}", start);
	expect(end, `${name}(): unterminated body`).toBeGreaterThan(start);
	return src.slice(start, end + 2);
}

function isTargetWith(selected) {
	const body = `${fnSource("isTarget")}\nreturn isTarget;`;
	return new Function("selected", body)({ value: selected });
}

const LINE = "WIP.1-Bo'lim - A";
const OTHER = "WIP.4-Bo'lim - A";
const chip = { name: "MFG-WO-0001", line: LINE, planned_start_date: "2026-08-28 09:30:00" };

describe("the planning board only offers moves the database will accept", () => {
	it("offers another day on the order's own line", () => {
		expect(isTargetWith(chip)(LINE, "2026-08-30")).toBe(true);
	});

	it("offers nothing on any other line", () => {
		// The whole reason the board is a grid and not a drag surface.
		expect(isTargetWith(chip)(OTHER, "2026-08-30")).toBe(false);
		expect(isTargetWith(chip)(OTHER, "2026-08-28")).toBe(false);
	});

	it("does not offer the square the order is already in", () => {
		// A no-op write that reports success is how a planner concludes the
		// board did something when it did not.
		expect(isTargetWith(chip)(LINE, "2026-08-28")).toBe(false);
	});

	it("offers nothing while nothing is picked", () => {
		expect(isTargetWith(null)(LINE, "2026-08-30")).toBe(false);
	});
});

describe("finished work is refused before the call, not after", () => {
	const frozen = new Function(
		`${src.slice(src.indexOf("const FROZEN ="), src.indexOf("\n", src.indexOf("const isFrozen =")))}\nreturn isFrozen;`
	)();

	it("refuses the three statuses whose planned date is a record of the past", () => {
		for (const status of ["Completed", "Closed", "Cancelled"]) {
			expect(frozen({ status }), status).toBe(true);
		}
	});

	it("lets unfinished work be moved", () => {
		for (const status of ["Draft", "Not Started", "In Process", "Stopped"]) {
			expect(frozen({ status }), status).toBe(false);
		}
	});
});

describe("the board draws no number nobody entered", () => {
	it("renders no load, capacity or hours figure", () => {
		// 0 of 3789 orders carry a planned_end_date and 0 submitted BOMs carry an
		// operating cost, so any of these would be derived from nothing — and a
		// percentage on a planning screen is read as a measurement and staffed
		// against.
		for (const invented of ["load", "capacity", "utilisation", "utilization", "hours"]) {
			expect(src).not.toContain(`cell.${invented}`);
			expect(src).not.toContain(`.${invented} }}`);
		}
	});

	it("shows the quantity that was typed instead", () => {
		expect(src).toContain("cell(line, day).qty");
	});
});
