/* Composable for canonical Tender Context Navigation (Task C2).
 *
 * Canonical Context Fields:
 *  - company: from session.activeCompany (NEVER trusted from query params)
 *  - tender: parent Tender Master ID (e.g. TND-2026-001)
 *  - deal: lot CRM Deal ID (e.g. LOT-A)
 *  - phase: funnel phase (e.g. awarded, submitted)
 *  - list filters: stage, period, risk, due, status, from_date, to_date
 */
import { computed } from "vue";
import { tenderRouteFilters } from "./tenderBoardFilters.js";

export const CONTEXT_QUERY_KEYS = [
	"tender",
	"deal",
	"phase",
	"stage",
	"period",
	"risk",
	"due",
	"status",
	"from_date",
	"to_date",
];

export function buildTenderQuery(currentQuery = {}, extra = {}) {
	const result = {};

	// Preserve canonical context keys from current query
	for (const key of CONTEXT_QUERY_KEYS) {
		const val = currentQuery[key];
		if (val !== undefined && val !== null && val !== "") {
			result[key] = String(val);
		}
	}

	// Merge extra params (excluding company to enforce session scoping)
	for (const [key, val] of Object.entries(extra)) {
		if (key === "company") continue; // Never trust company query injection
		if (val !== undefined && val !== null && val !== "") {
			result[key] = String(val);
		} else if (val === null || val === "") {
			delete result[key];
		}
	}

	return result;
}

export function useTenderContext(route) {
	const currentQuery = computed(() => route?.query || {});

	const activeTender = computed(() => currentQuery.value.tender || "");
	const activeDeal = computed(() => currentQuery.value.deal || "");
	const activePhase = computed(() => currentQuery.value.phase || "");
	const filters = computed(() => tenderRouteFilters(currentQuery.value));

	function queryWith(extra = {}) {
		return buildTenderQuery(currentQuery.value, extra);
	}

	function sourcingLocation(dealId, extra = {}) {
		const lot = dealId || activeDeal.value;
		return {
			name: "tender-sourcing",
			query: queryWith({ deal: lot, ...extra }),
		};
	}

	function documentsLocation(dealId, extra = {}) {
		const lot = dealId || activeDeal.value;
		return {
			name: "tender-documents",
			query: queryWith({ deal: lot, ...extra }),
		};
	}

	function poControlLocation(dealId, extra = {}) {
		const lot = dealId || activeDeal.value;
		return {
			name: "tender-po-control",
			query: queryWith({ deal: lot, ...extra }),
		};
	}

	function parentCrmLocation(tenderId, extra = {}) {
		const parent = tenderId || activeTender.value;
		return {
			name: "tender-crm",
			query: queryWith({ tender: parent, deal: "", ...extra }),
		};
	}

	return {
		activeTender,
		activeDeal,
		activePhase,
		filters,
		queryWith,
		sourcingLocation,
		documentsLocation,
		poControlLocation,
		parentCrmLocation,
	};
}
