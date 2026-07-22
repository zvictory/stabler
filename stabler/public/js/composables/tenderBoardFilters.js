const FILTER_KEYS = ["stage", "period", "risk", "due", "status"];

export function tenderRouteFilters(query = {}) {
	return Object.fromEntries(
		FILTER_KEYS.map((key) => [key, String(query[key] || "")]),
	);
}

export function activeTenderFilters(filters) {
	return FILTER_KEYS
		.filter((key) => filters[key] && filters[key] !== "all")
		.map((key) => [key, filters[key]]);
}

function matchesPeriod(eventDate, period) {
	return !period || String(eventDate || "").slice(0, 7) === period;
}

function matchesStage(row, stage) {
	if (!stage || stage === "all") return true;
	if (row.lifecycle) return Boolean(row.lifecycle[stage]);
	return row.stage === stage;
}

export function filterTenderRows(rows, filters) {
	return (rows || []).filter((row) =>
		matchesPeriod(row.event_date || row.transaction_date, filters.period) &&
		matchesStage(row, filters.stage) &&
		(!filters.risk || row.risk === filters.risk) &&
		(!filters.due || row.due === filters.due) &&
		(!filters.status || filters.status === "all" || row.status === filters.status),
	);
}
