import { describe, expect, it } from "vitest";

import { accountLabel, accountTypeLabel } from "../composables/accounts.js";

// The fixture these read lives in tests/setup.js. `MIKAS USD` is not in it, on
// purpose — see below.

describe("accountLabel — the chart of accounts in the reader's language", () => {
	// Account names are database values, so they never passed through the
	// harvester's literal `t("...")` scan and every screen rendered them raw. On
	// the one screen where the vocabulary IS the product, a Russian user read
	// "Application of Funds (Assets)" over "Bank Accounts" in English.
	it("translates a group name", () => {
		expect(accountLabel({ account_name: "Bank Accounts" })).toBe("Банковские счета");
	});

	it("translates a leaf name", () => {
		expect(accountLabel({ account_name: "Retained Earnings" })).toBe("Нераспределённая прибыль");
	});

	// This is the whole safety mechanism, not a nicety. The catalogue lists
	// accounting vocabulary and nothing else; a counterparty, a bank or a
	// company's own coinage is absent from it and must reach the screen exactly
	// as the ledger spells it. Translating "MIKAS USD" would name an account
	// that does not exist.
	it("leaves a name the catalogue does not carry exactly as the ledger spells it", () => {
		expect(accountLabel({ account_name: "MIKAS USD" })).toBe("MIKAS USD");
		expect(accountLabel({ account_name: "Aidia ipak yo'li" })).toBe("Aidia ipak yo'li");
	});

	// Not every payload carries account_name — some endpoints return only the
	// docname. Falling back to it beats rendering an empty cell.
	it("falls back to the docname when the row carries no account_name", () => {
		expect(accountLabel({ name: "Bank Accounts" })).toBe("Банковские счета");
		expect(accountLabel({ name: "1110 - Kassa - M" })).toBe("1110 - Kassa - M");
	});

	it("accepts a bare string, which is how the ledger header passes it", () => {
		expect(accountLabel("Bank Accounts")).toBe("Банковские счета");
	});

	// The call sites read `accountLabel(x) || x.account`, so an empty string
	// rather than "undefined" is what keeps those fallbacks working.
	it.each([[null], [undefined], [{}], [{ account_name: "" }], [""]])("returns an empty string for %p", (input) => {
		expect(accountLabel(input)).toBe("");
	});
});

describe("accountTypeLabel — a fixed enum is still a label", () => {
	it("translates an account type", () => {
		expect(accountTypeLabel("Receivable")).toBe("Дебиторская задолженность");
	});

	it("renders nothing when an account has no type, rather than an empty badge", () => {
		expect(accountTypeLabel("")).toBe("");
		expect(accountTypeLabel(null)).toBe("");
	});
});
