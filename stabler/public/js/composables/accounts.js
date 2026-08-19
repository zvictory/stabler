import { t } from "./i18n.js";

/**
 * An account's name, in the reader's language.
 *
 * Account names live in the database, so they never passed through the
 * harvester's `t("literal")` scan and every screen rendered them raw. A Russian
 * user reading a Chart of Accounts got "Application of Funds (Assets)" over
 * "Current Assets" over "Bank Accounts" — the one screen in the app where the
 * vocabulary IS the product, in a language they may not read.
 *
 * Translating at display time rather than renaming the records keeps one chart
 * serving all five languages, leaves the docnames (and every GL Entry, Payment
 * Entry and Link field that quotes them) untouched, and is reversible by
 * deleting a CSV row. The names themselves are seeded into the catalogues by
 * translations/add_coa_translations.py, since a dynamic `t(x)` is invisible to
 * the harvester. Anything not in the catalogue — a counterparty, a bank, a
 * company's own coinage — falls through to what the ledger actually says.
 */
export function accountLabel(row) {
	if (!row) return "";
	if (typeof row === "string") return t(row);
	const source = row.account_name || row.name || "";
	return source ? t(source) : "";
}

/** An `account_type` value, which is a fixed English enum, not free text. */
export function accountTypeLabel(type) {
	return type ? t(type) : "";
}

/**
 * Which currency a not-yet-created account starts in.
 *
 * The opening-balance field takes its decimal precision from this value, so an
 * unnamed currency must never be substituted behind the user's back. Measured on
 * mikas.erpstable.com 2026-08-19: the modal read "Account currency: —" while the
 * field was handed the company currency (UZS, zero decimals), and 1500000.50
 * typed before USD was chosen became 1500001 in the model — not just on screen.
 *
 * The parent's currency wins because a child of "Банк USD" is a USD account, and
 * that is the case the fallback was destroying.
 */
export function newAccountCurrency(parentNode, companyCurrency) {
	return (parentNode && parentNode.account_currency) || companyCurrency || "";
}

/**
 * Whether `node` matches a Chart of Accounts search term.
 *
 * Measured on the COA page: the search box matched only `account_name` /
 * `account_number` / `name` — all raw English docfield values — while the row
 * on screen renders `accountLabel(node)`, the translated string. A Russian
 * user typing what they can read ("наличные") got "No matches found" for an
 * account labeled "Наличные" on screen. Adding the translated label to the
 * match set is what makes "search what you see" actually true.
 */
export function matchesAccountSearch(node, term) {
	if (!term) return true;
	const needle = String(term).toLowerCase();
	return (
		(node.account_name || "").toLowerCase().includes(needle) ||
		String(node.account_number || "").toLowerCase().includes(needle) ||
		(node.name || "").toLowerCase().includes(needle) ||
		accountLabel(node).toLowerCase().includes(needle)
	);
}

/**
 * The chain of ancestor labels above `node`, root first, translated, joined
 * with " › ". Does not include `node` itself.
 *
 * Needed because a search that flattens the tree drops every non-matching
 * ancestor, but the row's indentation used to stay put — three "Kassa"
 * results could land at the same visual depth with nothing above them saying
 * which is Assets › Current Assets › Cash and which is a Liability contra
 * account. `accountsByName` is the flat account list keyed by `name`.
 */
export function accountAncestorPath(node, accountsByName) {
	const path = [];
	let parentName = node && node.parent_account;
	const seen = new Set();
	while (parentName && accountsByName[parentName] && !seen.has(parentName)) {
		seen.add(parentName);
		const parent = accountsByName[parentName];
		path.unshift(accountLabel(parent));
		parentName = parent.parent_account;
	}
	return path.join(" › ");
}

/**
 * A Select option label for `node` that carries its whole position in the
 * tree — "Asset › Current Assets › Bank Accounts" — rather than a bare name.
 *
 * Select.vue searches an option's `label` text (see the searchKeys fallback
 * in Select.vue), so building the path into the label is what makes the
 * parent picker searchable by branch, not just by the leaf name — two groups
 * named "Прочие расходы" and "Прочие" stop being indistinguishable.
 */
export function accountOptionPath(node, accountsByName) {
	const parts = [];
	if (node.root_type) parts.push(t(node.root_type));
	const ancestors = accountAncestorPath(node, accountsByName);
	if (ancestors) parts.push(ancestors);
	parts.push(accountLabel(node));
	return parts.join(" › ");
}

// Root types whose normal balance is a CREDIT. GL Entry / account_summary
// always return SUM(debit - credit), so these three read negative under a
// perfectly normal balance — see applyRootTypeSign.
const CREDIT_NORMAL_ROOT_TYPES = new Set(["Liability", "Equity", "Income"]);

/**
 * Flip a raw `debit - credit` balance into the sign a human expects to read
 * for `rootType`.
 *
 * `account_summary`'s own docstring says "caller renders sign as appropriate"
 * — the Chart of Accounts page never did. A perfectly normal 45,000,000 UZS
 * payable came back as -45,000,000 and was painted red, and every Liability /
 * Equity / Income balance and roll-up did the same: roughly 40% of the page
 * was a permanent wall of red carrying zero information.
 */
export function applyRootTypeSign(value, rootType) {
	if (typeof value !== "number") return value;
	return CREDIT_NORMAL_ROOT_TYPES.has(rootType) ? -value : value;
}

/**
 * Whether a balance is genuinely abnormal for its root type — i.e. still
 * negative AFTER `applyRootTypeSign`. This, not a raw `< 0` check, is the
 * only thing red should ever mean on the Chart of Accounts: an overdrawn
 * asset, a debit-balance payable, a loss-making income account. Group rows
 * are never colored by this — callers must gate on `!node.is_group` — a
 * roll-up mixing normal and abnormal children is not itself "abnormal".
 */
export function isAbnormalBalance(value, rootType) {
	if (typeof value !== "number") return false;
	return applyRootTypeSign(value, rootType) < 0;
}
