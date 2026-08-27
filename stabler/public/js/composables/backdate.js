import { ref } from "vue";
import { call } from "../api/client.js";

// Whether the signed-in user may post a document dated before today.
//
// The rule is not Stabler's. `stable_app` binds `block_backdated_writes` to
// `validate` on eight doctypes — Sales Order, Sales Invoice, Purchase Invoice,
// Payment Entry, Stock Entry, Journal Entry, Delivery Note, Purchase Receipt —
// and throws for anyone who is not Administrator or System Manager. It also
// ships `can_backdate()`, whose own docstring calls it the "frontend hint
// endpoint — UI uses this to show/hide backdate widgets". Nothing in the SPA
// ever called it, so every date picker offered a value the server refuses.
//
// That gap was survivable while `create_stock_entry` dropped the operator's
// date on the floor: without `set_posting_time`, the ERPNext controller reset
// posting_date to now and the guard never saw a past date to refuse. Setting
// the flag (inventory.py, 2026-08-27) fixed the silent date loss and, in doing
// so, turned the guard on for real — the same change surfaced it on Payment
// Entry as three refusals within minutes of the restart.
//
// The hook stays the source of truth. This only stops the UI promising what
// the server will not accept.

// `true` until told otherwise, in both directions:
//
//   * The form renders before the answer arrives. Starting closed would flash
//     a disabled past at every user for one round trip, administrators
//     included.
//   * `stable_app` is installed on production and on no development bench, so
//     the call fails outright on genesis-test and on every local site. A site
//     without the app has no backdating rule to obey.
//
// A wrong `true` costs one honest error message from the hook. A wrong `false`
// silently removes a permission the user actually holds, with nothing on
// screen to say why — which is the failure this file exists to prevent, aimed
// the other way.
const allowed = ref(true);
let asked = false;

/**
 * Reactive answer to "may this user post to an earlier date?".
 *
 * Asks the server on first use and caches for the page load — the permission
 * is a role check, and roles do not change under a session.
 *
 * @returns {import("vue").Ref<boolean>}
 */
export function useCanBackdate() {
	if (!asked) {
		asked = true;
		call("stable_app.api.guards.can_backdate")
			.then((res) => {
				allowed.value = Boolean(res?.can_backdate);
			})
			.catch(() => {
				// No such endpoint, or no network. Leave the capability alone.
			});
	}
	return allowed;
}

/**
 * The earliest date a posting-date picker should offer.
 *
 * `min` rather than `disabled`: the field stays usable for the date the user
 * is allowed to pick — today — and excludes exactly what the server refuses.
 *
 * @param {boolean} canBackdate
 * @param {string} today ISO yyyy-mm-dd
 * @returns {string} ISO yyyy-mm-dd, or "" for an unbounded calendar
 */
export function earliestPostingDate(canBackdate, today) {
	return canBackdate ? "" : today;
}
