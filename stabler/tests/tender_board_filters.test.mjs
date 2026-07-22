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
		event_date: "2026-07-10",
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
	["TENDER-READY"],
	"stage and period must intersect using lifecycle and event-date evidence",
);
assert.deepEqual(
	filterTenderRows(lifecycleRows, { status: "won", period: "2026-07" }).map((row) => row.deal),
	["TENDER-READY"],
	"status and period must intersect using returned row evidence",
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
