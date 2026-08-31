/* What an RFQ invitation reaches — the client-side twin of `_sourcing_reach.py`.
 *
 * The saved side is counted on the server and arrives on `list_rfqs().reach`.
 * This exists for the set that has not been saved yet: the vendors sitting in
 * the RFQ form right now, where the officer can still change their mind and no
 * document exists to ask the server about.
 *
 * It is a deliberate second implementation of one rule, so it is kept to the
 * shape of the first — same keys, same "a blank country is not a country" — and
 * pinned by its own spec. If the two ever disagree, the badge on the form and
 * the badge on the workspace will say different things about the same vendors,
 * which is the drift this module's Python twin was written to avoid.
 *
 * Not a ceiling: a quotation from an uninvited vendor can still be attached to
 * the lot later, so wording built on this must say "this invitation".
 */

export function reachOf(invited, minSuppliers, minCountries) {
	const countriesBySupplier = new Map();
	for (const row of invited || []) {
		const supplier = String(row?.supplier ?? "").trim();
		if (!supplier) continue;
		if (!countriesBySupplier.has(supplier)) countriesBySupplier.set(supplier, new Set());
		const country = String(row?.country ?? "").trim();
		if (country) countriesBySupplier.get(supplier).add(country);
	}

	const countries = new Set();
	let unknownCountry = 0;
	for (const known of countriesBySupplier.values()) {
		if (known.size === 0) unknownCountry += 1;
		for (const c of known) countries.add(c);
	}

	return {
		suppliers: countriesBySupplier.size,
		countries: countries.size,
		unknown_country: unknownCountry,
		meets_suppliers: countriesBySupplier.size >= minSuppliers,
		meets_countries: countries.size >= minCountries,
	};
}
