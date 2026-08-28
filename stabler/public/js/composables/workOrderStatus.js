// One status vocabulary for both work order screens.
//
// The list and the detail page each carried their own status→colour map and
// they disagreed on three of seven: a Draft order read yellow in the list and
// grey on its own page, a Cancelled one grey in the list and red on the page,
// a Stopped one grey in the list and orange on the page. Same order, same
// stored status, a different answer depending on which screen the supervisor
// was standing in front of. The detail page also printed the stored English
// through, which is the defect the list's labels were written to remove.
//
// Where the two maps disagreed the resolution favours whichever told the
// operator more: Stopped is orange and Cancelled red because the list painted
// both the same grey as a Draft, and a halted order is not a neutral state —
// it is the one on the board that needs somebody. Not Started keeps the list's
// yellow: on a production board the order that has not begun is exactly what
// wants attention.

import { computed } from "vue";
import { t } from "./i18n.js";
import { getStatusBadgeClass } from "./status.js";

/** The raw ERPNext statuses these screens filter by. "" means "all". */
export const WORK_ORDER_STATUSES = [
	"",
	"Draft",
	"Not Started",
	"In Process",
	"Completed",
	"Stopped",
	"Closed",
	"Cancelled",
];

export function useWorkOrderStatus() {
	// ERPNext stores the status in English. A Russian-speaking supervisor reads
	// a translated column header and then one untranslated word inside it — the
	// one word that says what to do next.
	const statusLabels = computed(() => ({
		Draft: t("Draft"),
		"Not Started": t("Not Started"),
		"In Process": t("In Process"),
		Completed: t("Completed"),
		Stopped: t("Stopped"),
		Closed: t("Closed"),
		Cancelled: t("Cancelled"),
	}));

	/** A stored status as the operator should read it; unknown values pass through. */
	const statusLabel = (s) => statusLabels.value[s] || s || "";

	const statusBadge = (s) => getStatusBadgeClass("Work Order", s);

	const statusOptions = computed(() =>
		WORK_ORDER_STATUSES.map((s) => ({ value: s, label: statusLabel(s) || t("All statuses") })),
	);

	return { statusLabels, statusLabel, statusBadge, statusOptions };
}
