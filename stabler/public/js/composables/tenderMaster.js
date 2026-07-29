const CRM_STAGES = ["New", "Sourcing", "Bid Preparation", "Submitted", "Closed"];

const CLOSED_STATUSES = new Set(["Won", "Lost", "Cancelled", "Closed"]);

export function createLatestRequestGuard() {
	let latestRequest = 0;
	return {
		start() {
			latestRequest += 1;
			return latestRequest;
		},
		isLatest(request) {
			return request === latestRequest;
		},
	};
}

export function normalizeTenderMaster(record = {}) {
	const status = record.status || "New";
	return {
		...record,
		buyer: record.buyer_name || "",
		deadline: record.submission_deadline || "",
		documentReadiness: record.document_readiness,
		estimatedTotal: record.estimated_total ?? 0,
		lotCount: record.lot_count ?? 0,
		owner: record.owner_user || "",
		stage: CLOSED_STATUSES.has(status) ? "Closed" : status,
		tenderNumber: record.tender_number || record.name || "",
		title: record.title || "",
	};
}

export function groupTenderMasters(records = []) {
	const groups = CRM_STAGES.map((key) => ({ key, records: [] }));
	const byKey = new Map(groups.map((group) => [group.key, group]));

	for (const record of records) {
		const normalized = normalizeTenderMaster(record);
		const group = byKey.get(normalized.stage) || byKey.get("New");
		group.records.push(normalized);
	}

	return groups;
}
