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
