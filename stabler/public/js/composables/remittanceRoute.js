/**
 * One way to write a remittance route, because two screens show the same thing.
 *
 * The design of record spells the format out once —
 * `Tashkent · TAS-C -> Istanbul · IST-1` (docs/plans/PROMPT_remittance_design_v2.txt:47-49
 * for the quote panel, :141 for the Operations table) — and the two screens that
 * render it were drifting: the quote panel had no route row at all, and
 * Operations stacks `branch -> branch` over `city -> city` on two lines. Fixing
 * them separately would have produced two spellings of one sentence.
 *
 * NOT the same as `deskLabel` inside NewRemittanceV1.vue, and deliberately not
 * merged with it: that one writes `TAS-C — Tashkent` for the desk SELECTOR,
 * where the branch code is what the cashier is picking and belongs first. Here
 * the city leads, because a route is read as places before codes.
 */

const SEPARATOR = " · ";
const ARROW = " → ";
const MISSING = "—";

/**
 * `{city} · {branch}` — or whichever half exists.
 *
 * A desk is `{ branch, city }`; both halves are optional in the data, since
 * `city` is filled from whichever Remittance Settings row carried one and a desk
 * configured without a city is legal.
 */
export function routeDeskLabel(desk) {
	if (!desk) return "";
	const city = (desk.city || "").trim();
	const branch = (desk.branch || "").trim();
	if (city && branch) return `${city}${SEPARATOR}${branch}`;
	return city || branch || "";
}

/**
 * `Tashkent · TAS-C → Istanbul · IST-1`.
 *
 * Returns "" when NEITHER end is known, so a caller can drop the row rather than
 * render a lone arrow. One known end still renders, with the unknown side shown
 * as an em dash: half a route is information, and hiding it would read as "no
 * route" on a transfer that has one.
 */
export function routeLabel(origin, destination) {
	const from = routeDeskLabel(origin);
	const to = routeDeskLabel(destination);
	if (!from && !to) return "";
	return `${from || MISSING}${ARROW}${to || MISSING}`;
}

/**
 * `USD → EUR`, and "" when the two legs are the same currency.
 *
 * Same-currency transfers are ordinary here, and `USD → USD` reads as a bug to
 * the cashier rather than as a fact about the transfer.
 */
export function currencyLegs(sendCurrency, receiveCurrency) {
	const send = (sendCurrency || "").trim();
	const receive = (receiveCurrency || "").trim();
	if (!send || !receive || send === receive) return "";
	return `${send}${ARROW}${receive}`;
}
