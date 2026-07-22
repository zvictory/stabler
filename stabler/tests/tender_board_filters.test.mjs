import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync("stabler/public/js/composables/tenderBoardFilters.js", "utf8");
const module = new vm.SourceTextModule(source, { identifier: "tenderBoardFilters.js" });
await module.link(() => {
	throw new Error("The filter helper must not import runtime dependencies.");
});
await module.evaluate();

const { activeTenderFilters, filterTenderRows } = module.namespace;

const lifecycleRows = [
		{
			deal: "TENDER-READY",
			event_date: "2026-05-10",
			event_dates: {
				identified: "2026-05-10",
				decided: "2026-06-02",
				go: "2026-06-02",
				ready: "2026-06-02",
				submitted: "2026-07-10",
				won: "2026-08-12",
				result: "2026-08-12",
			},
		lifecycle: { identified: true, decided: true, go: true, ready: true, submitted: true, assigned: true },
		status: "won",
		risk: "good",
		due: "on_time",
	},
	{
		deal: "TENDER-OLD",
		event_date: "2026-06-30",
		lifecycle: { identified: true, decided: true, go: true, ready: false, submitted: false, assigned: false },
		status: "pending",
		risk: "warn",
		due: "soon",
	},
];

assert.deepEqual(
	filterTenderRows(lifecycleRows, { stage: "ready", period: "2026-07" }).map((row) => row.deal),
	[],
	"ready must use its June decision date, not the later submission/result date",
);
assert.deepEqual(
	filterTenderRows(lifecycleRows, { stage: "submitted", period: "2026-07" }).map((row) => row.deal),
	["TENDER-READY"],
	"submitted must use its own July timestamp",
);
assert.deepEqual(
	filterTenderRows(lifecycleRows, { stage: "submitted", status: "won", period: "2026-07" }).map((row) => row.deal),
	["TENDER-READY"],
	"a stage/status intersection must keep the selected stage's event date",
);
assert.deepEqual(
	filterTenderRows(lifecycleRows, { status: "won", period: "2026-08" }).map((row) => row.deal),
	["TENDER-READY"],
	"result status must use its own August timestamp",
);

const customsRows = [
	{ po: "PO-JULY", event_date: "2026-07-03", stage: "in_progress", status: "in_progress", risk: "warn", due: "soon" },
	{ po: "PO-JUNE", event_date: "2026-06-30", stage: "cleared", status: "cleared", risk: "good", due: "on_time" },
];
assert.deepEqual(
	filterTenderRows(customsRows, { status: "in_progress", period: "2026-07" }).map((row) => row.po),
	["PO-JULY"],
	"customs status and period must narrow on PO evidence",
);

const logisticsRows = [
	{ po: "PO-LATE", event_date: "2026-07-18", stage: "late", status: "late", risk: "risk", due: "late" },
	{ po: "PO-DELIVERED", event_date: "2026-07-01", stage: "delivered", status: "delivered", risk: "good", due: "on_time" },
];
assert.deepEqual(
	filterTenderRows(logisticsRows, { status: "late", period: "2026-07" }).map((row) => row.po),
	["PO-LATE"],
	"logistics status and period must narrow on PO evidence",
);
assert.deepEqual(
	activeTenderFilters({ stage: "", period: "2026-07", risk: "", due: "", status: "all" }),
	[["period", "2026-07"]],
	"neutral status=all is not shown as an active no-op filter",
);

console.log("tender board filter behavior: OK");
