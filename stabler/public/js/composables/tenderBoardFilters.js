const FILTER_KEYS = ["stage", "period", "risk", "due", "status", "from_date", "to_date"];

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

function lifecycleEventDate(row, filters) {
	if (!row.event_dates) return row.event_date || row.transaction_date;
	if (filters.stage && filters.stage !== "all") {
		return row.event_dates[filters.stage];
	}
	if (filters.status && filters.status !== "all") {
		return row.event_dates[filters.status] || row.event_dates.result;
	}
	return row.event_dates.identified;
}

function matchesStage(row, stage) {
	if (!stage || stage === "all") return true;
	if (row.lifecycle) return Boolean(row.lifecycle[stage]);
	return row.stage === stage;
}

export function filterTenderRows(rows, filters) {
	return (rows || []).filter((row) => {
		const eventDate = String(lifecycleEventDate(row, filters) || "").slice(0, 10);
		return matchesPeriod(eventDate, filters.period) &&
		(!filters.from_date || eventDate >= filters.from_date) &&
		(!filters.to_date || eventDate <= filters.to_date) &&
		matchesStage(row, filters.stage) &&
		(!filters.risk || row.risk === filters.risk) &&
		(!filters.due || row.due === filters.due) &&
		(!filters.status || filters.status === "all" || row.status === filters.status);
	});
}
