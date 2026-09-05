import { t } from "./i18n.js";
import { getDocstatusLabel, getStatusBadgeClass } from "./status.js";

/**
 * The status badge for a Request for Quotation, shared by the list and the
 * detail page (review follow-up, P2/P3) -- before this module existed the two
 * screens each resolved the badge their own way and could disagree: the list
 * read raw `docstatus` and showed "Draft" for the same RFQ the detail page
 * already read as "Sent".
 *
 * An RFQ that is still a draft doubles the badge as the "did we send it"
 * signal. `mark_rfq_sent` (sourcing.py) never submits the RFQ -- the
 * draft-and-stop philosophy -- so `docstatus` alone cannot tell "drafted"
 * from "drafted and handed to suppliers" apart; that gap is UAT G.13.
 * `get_rfq`, `list_rfqs` and `list_all_rfqs` all carry `sent_count`, read
 * back from the Communications `mark_rfq_sent` writes, and this is the one
 * place that turns it into a badge.
 */
export function rfqStatusBadge(doc) {
	const docstatus = Number(doc?.docstatus) || 0;
	if (docstatus === 0 && Number(doc?.sent_count) > 0) {
		return { label: t("Sent"), badgeClass: getStatusBadgeClass("Request for Quotation", "Sent") };
	}
	return {
		label: getDocstatusLabel(docstatus),
		badgeClass: getStatusBadgeClass("Request for Quotation", docstatus),
	};
}
