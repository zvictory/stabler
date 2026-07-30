// Board lanes, in business order. MUST stay identical to LANES in
// stabler/api/_tender_master_state.py — the backend derives a record's lane from
// its child lots and sends it as `stage`; a lane the SPA doesn't know would drop
// its tenders into the first column and silently understate the pipeline.
export const LANES = ["Preparation", "Active", "Awaiting Result", "Partial Result", "Completed"];

const LIST_QUERY_KEYS = ["status", "stage", "risk", "deal", "from_date", "to_date"];

export function tenderMasterListParams(query = {}) {
	return Object.fromEntries(
		LIST_QUERY_KEYS.flatMap((key) => {
			const value = query[key];
			return typeof value === "string" && value ? [[key, value]] : [];
		})
	);
}

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
	return {
		...record,
		buyer: record.buyer_name || "",
		deadline: record.submission_deadline || "",
		documentReadiness: record.document_readiness,
		// Earliest bid deadline among the still-open lots — the parent's own
		// submission_deadline says nothing about which lot is due next.
		earliestDeadline: record.earliest_deadline || "",
		// DERIVED from the child lots, so the number on the card is always the one
		// the drill-down adds up to — including when the drill-down is empty.
		// Falling back to the parent's typed `estimated_total` while `lot_count` is
		// 0 read as safe ("no lots to contradict it"), but `lot_count` counts only
		// the lots this user may READ: someone whose permissions hide every lot got
		// the typed figure on the card and 0.00 in the detail summary, which takes
		// `lot_estimated_total` unconditionally. `lot_count` cannot tell "no lots"
		// from "no permitted lots", so it cannot gate this. The typed field stays in
		// the payload untouched — that is what a tender edit form writes back.
		estimatedTotal: record.lot_estimated_total ?? 0,
		lostLotCount: record.lost_lot_count ?? 0,
		lotCount: record.lot_count ?? 0,
		// Open = not won and not lost, so open + won + lost = lotCount. Lots
		// awaiting a result are a SUBSET of open, never a fourth bucket.
		openLotCount: record.open_lot_count ?? 0,
		owner: record.owner_user || "",
		policyGapCount: record.policy_gap_count ?? 0,
		riskCount: record.risk_count ?? 0,
		// The lane is DERIVED by the backend from the child lots
		// (_tender_master_state.derive). The parent's hand-typed `status` must
		// never decide it: nobody reliably re-types the parent when a lot moves,
		// so a status-driven board shows "New" next to two won lots.
		stage: LANES.includes(record.stage) ? record.stage : LANES[0],
		submittedLotCount: record.submitted_lot_count ?? 0,
		tenderNumber: record.tender_number || record.name || "",
		title: record.title || "",
		wonLotCount: record.won_lot_count ?? 0,
	};
}

export function groupTenderMasters(records = []) {
	const groups = LANES.map((key) => ({ key, records: [] }));
	const byKey = new Map(groups.map((group) => [group.key, group]));

	for (const record of records) {
		const normalized = normalizeTenderMaster(record);
		const group = byKey.get(normalized.stage) || byKey.get(LANES[0]);
		group.records.push(normalized);
	}

	return groups;
}
