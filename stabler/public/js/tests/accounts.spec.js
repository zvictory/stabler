import { describe, expect, it } from "vitest";

import {
	accountLabel,
	accountTypeLabel,
	applyRootTypeSign,
	isAbnormalBalance,
	newAccountCurrency,
} from "../composables/accounts.js";

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

describe("newAccountCurrency", () => {
	// Measured live on mikas.erpstable.com, 2026-08-19: the create-account modal
	// showed "Account currency: —" while handing the opening-balance field the
	// COMPANY currency as a fallback. Mikas is UZS, UZS carries zero decimals, so
	// the field snapped the model to a whole number on blur. Typing 1500000.50
	// before choosing USD produced 1500001 — in the model, not just on screen —
	// and picking USD afterwards did not bring the decimals back. The form never
	// said it was treating the account as UZS.
	//
	// So the currency is named up front instead of substituted invisibly, and it
	// is the parent's where the parent has one: a child of "Банк USD" is a USD
	// account, which is exactly the case that was losing money.
	it("inherits the parent group's currency", () => {
		expect(newAccountCurrency({ name: "Банк USD", account_currency: "USD" }, "UZS")).toBe("USD");
	});

	it("falls back to the company currency when the parent has none", () => {
		expect(newAccountCurrency({ name: "Assets", account_currency: null }, "UZS")).toBe("UZS");
	});

	it("uses the company currency at the root", () => {
		expect(newAccountCurrency(null, "UZS")).toBe("UZS");
	});

	it("never invents a currency out of nothing", () => {
		// An empty string leaves MoneyInput on its two-decimal default, which
		// keeps the typed value intact. Guessing here is what caused the bug.
		expect(newAccountCurrency(null, "")).toBe("");
		expect(newAccountCurrency(undefined, undefined)).toBe("");
	});
});

describe("applyRootTypeSign / isAbnormalBalance — red means something again", () => {
	// account_summary's docstring: "Caller renders sign as appropriate". A
	// normal 45,000,000 UZS Payable balance is SUM(debit - credit) = -45,000,000
	// on the wire; that is not the sign a human reads a payable in.
	it("flips a Liability/Equity/Income balance, so a normal credit balance reads positive", () => {
		expect(applyRootTypeSign(-45000000, "Liability")).toBe(45000000);
		expect(applyRootTypeSign(-100, "Equity")).toBe(100);
		expect(applyRootTypeSign(-100, "Income")).toBe(100);
	});

	it("leaves Asset/Expense balances alone — their normal balance is already a debit", () => {
		expect(applyRootTypeSign(500, "Asset")).toBe(500);
		expect(applyRootTypeSign(500, "Expense")).toBe(500);
	});

	it("passes through non-numbers (null balance = not loaded yet) unchanged", () => {
		expect(applyRootTypeSign(null, "Liability")).toBe(null);
		expect(applyRootTypeSign(undefined, "Asset")).toBe(undefined);
	});

	it("a normal payable is not abnormal, even though its raw wire value is negative", () => {
		expect(isAbnormalBalance(-45000000, "Liability")).toBe(false);
	});

	it("a payable that is genuinely in debit (overpaid) IS abnormal", () => {
		// raw -(-100) after the flip is negative: a Liability account with a
		// debit balance, which is the one case red should still mean something.
		expect(isAbnormalBalance(100, "Liability")).toBe(true);
	});

	it("an overdrawn asset account is abnormal", () => {
		expect(isAbnormalBalance(-500, "Asset")).toBe(true);
	});

	it("null/undefined balances are never flagged abnormal", () => {
		expect(isAbnormalBalance(null, "Asset")).toBe(false);
	});
});
