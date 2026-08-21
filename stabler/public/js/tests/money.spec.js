import { describe, expect, it } from "vitest";

import {
	balanceState,
	formatCompactMoney,
	formatMoney,
	groupMoneyWhileTyping,
	moneyEpsilon,
	moneySeparators,
	parseMoneyInput,
} from "../composables/money.js";

// Grouping separators come from ICU, and ICU changes them between Node releases
// (ru-RU has shipped both U+00A0 and U+202F). Pinning the exact code point would
// make these tests fail on a Node upgrade without any contract having changed.
// What the rule actually promises is "grouped by a space", so normalise the
// space and assert that.
// (escaped, not literal: ESLint's no-irregular-whitespace rightly objects to a
// raw NBSP in source, and you cannot tell the two apart by eye anyway.)
const norm = (s) => s.replace(/[\u00a0\u202f]/g, " ");

describe("formatMoney — the display half of the money-input contract", () => {
	// ~/.claude/rules/money-input.md fixes these four groupings by name. They are
	// not cosmetic: a Turkish user reading "20.820" as twenty-thousand and a
	// Russian user reading it as twenty-point-eight-two is the failure mode.
	it.each([
		["en", "$20,820.00"],
		["ru", "20 820,00 $"],
		["uz", "20 820,00 $"],
		["uzc", "20 820,00 $"],
		["tr", "$20.820,00"],
	])("groups 20820 the way %s users write it", (language, expected) => {
		expect(norm(formatMoney(20820, "USD", language))).toBe(expected);
	});

	it("treats uz and uzc as ru — Uzbek has no separate CLDR grouping in use here", () => {
		expect(formatMoney(20820, "USD", "uz")).toBe(formatMoney(20820, "USD", "ru"));
		expect(formatMoney(20820, "USD", "uzc")).toBe(formatMoney(20820, "USD", "ru"));
	});

	it("falls back to en-US for a language the SPA does not ship", () => {
		expect(formatMoney(20820, "USD", "de")).toBe(formatMoney(20820, "USD", "en"));
	});

	// UZS carries two decimals because THE LEDGER DOES. The tiyin did leave
	// circulation in 1994, and this app spent a long time treating that as the
	// display rule — but ERPNext's precision is not an ISO fact, it is a site
	// setting: `currency_precision` is unset on every tenant and
	// `use_number_format_from_currency` is 0, so `get_field_precision` falls
	// through to the global "#,###.##" (frappe/model/meta.py:910-913). Measured
	// 2026-08-20: precision 2 for UZS on mikas AND anjan, and 197 721 of anjan's
	// 209 434 GL rows carry a fractional amount.
	//
	// So a whole-number display was not tidiness, it was a second number: the
	// form showed "1 500 001" and the ledger held 1 500 000,50. Showing what is
	// stored is the only version that cannot lie.
	it("prints UZS with two decimals and the native сўм suffix", () => {
		expect(norm(formatMoney(38000000, "UZS", "ru"))).toBe("38 000 000,00 сўм");
		expect(formatMoney(38000000, "UZS", "en")).toBe("38,000,000.00 сўм");
	});

	it("keeps the kopecks a UZS amount actually has", () => {
		expect(formatMoney(1000.6, "UZS", "en")).toBe("1,000.60 сўм");
	});

	// USDT is not ISO 4217, so Intl throws on it. The override exists precisely so
	// the crypto-settlement rows do not fall through to the bare toFixed() path.
	it("prints USDT with 2 decimals and a suffix, without Intl throwing", () => {
		expect(formatMoney(1234.5, "USDT", "en")).toBe("1,234.50 USDT");
	});

	it("degrades to a plain 2-decimal number for an unknown currency code", () => {
		expect(formatMoney(1234.5, "XYZQ", "en")).toBe("1234.50");
	});

	// An em dash, never "0.00" and never "NaN": a missing balance and a zero
	// balance mean different things to an accountant.
	it.each([[null], [undefined], [""], ["abc"], [NaN], [Infinity]])(
		"renders %p as an em dash, not as a number",
		(value) => {
			expect(formatMoney(value, "USD", "en")).toBe("—");
		}
	);

	it("renders a real zero as zero", () => {
		expect(formatMoney(0, "USD", "en")).toBe("$0.00");
	});

	it("accepts the numeric strings Frappe returns from the REST layer", () => {
		expect(formatMoney("20820", "USD", "en")).toBe("$20,820.00");
	});
});

describe("formatCompactMoney — dashboard tiles", () => {
	it("compacts in the reader's own language", () => {
		expect(formatCompactMoney(38000000, "USD", "en")).toBe("$38M");
		expect(norm(formatCompactMoney(38000000, "USD", "ru"))).toBe("38 млн $");
	});

	it("keeps the UZS suffix override in compact form too", () => {
		expect(norm(formatCompactMoney(38000000, "UZS", "ru"))).toBe("38 млн сўм");
	});

	it("renders an empty value as an em dash, same as formatMoney", () => {
		expect(formatCompactMoney(null, "USD", "en")).toBe("—");
	});
});

describe("balanceState — who owes whom", () => {
	// The sign convention is the whole point: positive = the party owes us,
	// negative = they paid ahead. Flipping it mislabels every party card.
	it("reads a positive balance as the party owing us", () => {
		expect(balanceState(1500)).toEqual({ state: "owes", abs: 1500 });
	});

	it("reads a negative balance as a prepayment, reported as a positive amount", () => {
		expect(balanceState(-1500)).toEqual({ state: "prepaid", abs: 1500 });
	});

	// Half a cent. Float arithmetic over hundreds of GL rows leaves dust like
	// 0.0000000001; without the threshold every settled party shows as "owes".
	it("treats sub-half-cent dust as settled and zeroes it out", () => {
		expect(balanceState(0.004)).toEqual({ state: "settled", abs: 0 });
		expect(balanceState(-0.004)).toEqual({ state: "settled", abs: 0 });
		expect(balanceState(0)).toEqual({ state: "settled", abs: 0 });
	});

	it("does not swallow half a cent and above", () => {
		expect(balanceState(0.006).state).toBe("owes");
	});

	it.each([[null], [undefined], [""], ["abc"]])("treats %p as settled", (value) => {
		expect(balanceState(value)).toEqual({ state: "settled", abs: 0 });
	});
});

describe("moneyEpsilon — how close counts as equal", () => {
	// These numbers must match `money_epsilon()` in stabler/api/_money.py exactly.
	// The client blocks "Pay Remaining" before the request, the server blocks it
	// again on arrival; if the two thresholds disagree, one of them lies to the
	// user — either a rejected payment the server would have taken, or a form
	// that submits only to throw.
	it("is half a cent for two-decimal currencies", () => {
		expect(moneyEpsilon("USD")).toBe(0.005);
		expect(moneyEpsilon("EUR")).toBe(0.005);
	});

	it("is half a kopeck for UZS, because the ledger stores kopecks", () => {
		// This was 0,5 — half a whole so'm — on the theory that UZS has no
		// fractional unit. ERPNext stores UZS at precision 2 on every tenant
		// (see the formatMoney block above), so 0,5 called forty kopecks of
		// real, recorded difference "rounding noise" and swallowed it.
		expect(moneyEpsilon("UZS")).toBe(0.005);
	});

	it("defaults to half a cent when the currency is unknown or missing", () => {
		expect(moneyEpsilon()).toBe(0.005);
		expect(moneyEpsilon("")).toBe(0.005);
	});
});

describe("parseMoneyInput — reading back what a human typed", () => {
	// The bug this suite exists for: MoneyInput treated "." as a thousands
	// separator for EVERY language except en, unconditionally. A Mikas user on
	// the Russian UI typing an opening balance of 1500000.50 got 150000050
	// posted to the ledger — a hundredfold error, silent until blur. The numeric
	// keypad's decimal key emits ".", so on ru/tr/uz/uzc it was not an edge
	// case: it was the only way most people tried to type a decimal.
	it.each(["ru", "uz", "uzc", "tr"])("reads a dot as the decimal point in %s when no locale says otherwise", (lang) => {
		expect(parseMoneyInput("1500000.50", lang)).toBe(1500000.5);
		expect(parseMoneyInput("12.5", lang)).toBe(12.5);
		expect(parseMoneyInput("0.75", lang)).toBe(0.75);
	});

	// The mirror image: a Russian-speaking user on the English UI types a comma.
	it("reads a comma as the decimal point in en when no locale says otherwise", () => {
		expect(parseMoneyInput("1500000,50", "en")).toBe(1500000.5);
		expect(parseMoneyInput("12,5", "en")).toBe(12.5);
	});

	// Both separators present: the LAST one is the decimal, whatever the locale.
	// This is how every human writes it and how every spreadsheet reads it.
	it("treats the last of two different separators as the decimal point", () => {
		expect(parseMoneyInput("1.500.000,50", "ru")).toBe(1500000.5);
		expect(parseMoneyInput("1,500,000.50", "en")).toBe(1500000.5);
		expect(parseMoneyInput("1,500,000.50", "ru")).toBe(1500000.5);
		expect(parseMoneyInput("1.500.000,50", "en")).toBe(1500000.5);
	});

	// Repeated separator can only be grouping — 1.500.000 is never 1.5.
	it("treats a repeated separator as grouping", () => {
		expect(parseMoneyInput("1.500.000", "ru")).toBe(1500000);
		expect(parseMoneyInput("1,500,000", "en")).toBe(1500000);
	});

	// The one genuinely ambiguous shape: a single separator followed by exactly
	// three digits. "1.500" is 1500 to a Russian and 1.5 to an American, and no
	// amount of cleverness resolves that — the locale has to decide. Documented
	// here so nobody "fixes" it later into a coin flip.
	it("lets the locale decide the one ambiguous shape: separator + exactly three digits", () => {
		expect(parseMoneyInput("1.500", "ru")).toBe(1500);
		expect(parseMoneyInput("1.500", "en")).toBe(1.5);
		expect(parseMoneyInput("1,500", "ru")).toBe(1.5);
		expect(parseMoneyInput("1,500", "en")).toBe(1500);
	});

	// The grouping characters Intl actually emits. Deleting these from the
	// cleanup class makes a value the component itself just rendered unreadable.
	it("strips the grouping whitespace Intl emits, including NBSP and NNBSP", () => {
		expect(parseMoneyInput("20 820,00", "ru")).toBe(20820);
		expect(parseMoneyInput("20 820,00", "ru")).toBe(20820);
		expect(parseMoneyInput("20 820,00", "ru")).toBe(20820);
		expect(parseMoneyInput("20'820.00", "en")).toBe(20820);
	});

	it("returns null for blank and unparseable input, so the field can stay empty", () => {
		expect(parseMoneyInput("", "ru")).toBeNull();
		expect(parseMoneyInput("   ", "ru")).toBeNull();
		expect(parseMoneyInput(null, "ru")).toBeNull();
		expect(parseMoneyInput("abc", "ru")).toBeNull();
		expect(parseMoneyInput(",", "ru")).toBeNull();
	});

	it("keeps a half-typed decimal readable so the caret is not trapped", () => {
		expect(parseMoneyInput("12,", "ru")).toBe(12);
		expect(parseMoneyInput("12.", "en")).toBe(12);
	});

	it("carries the sign", () => {
		expect(parseMoneyInput("-1500000.50", "ru")).toBe(-1500000.5);
	});
});

describe("grouping and parsing are one contract, read in both directions", () => {
	// Reported 2026-08-21 on Money -> Transfers: typing 1108000 and pressing Tab
	// left 110.8 in the field. Nothing in that screen's three-way binding can
	// produce 110.8 from 1108000 — the loss happens one layer down, between the
	// two halves of MoneyInput.
	//
	// With `group-while-typing`, MoneyInput regroups its own display on every
	// keystroke and the caret parks at the end, so the NEXT keystroke hands
	// `parseMoneyInput` a string this module wrote. Typing 1108000 in en walks
	// through "1,108" -> "1,1080" -> "11,0800" -> "110,8000", and the old rule
	// read that last lone comma as a decimal point: 110.8. The display still
	// said "1,108,000", so the field looked right until blur reformatted it
	// from the model. A UZS transfer of 1 108 000 would have posted as 110.8.
	//
	// ru/uz/uzc never saw it: their grouping mark is a non-breaking space, which
	// `parseMoneyInput` strips before it can be mistaken for anything. en and tr
	// group with the characters the parser has to disambiguate, so they carried
	// the whole bug — which is why "it works on my machine" was true.
	it.each(["en", "ru", "uz", "uzc", "tr"])(
		"survives a digit-by-digit entry of 1108000 in %s",
		(language) => {
			let display = "";
			let model = null;
			for (const ch of "1108000") {
				const text = display + ch; // caret parks at the end while grouping live
				model = parseMoneyInput(text, language);
				display = groupMoneyWhileTyping(text, language, 2);
			}
			expect(model).toBe(1108000);
		},
	);

	// The same defect stated directly, so a regression names itself instead of
	// arriving as a mysterious loop failure.
	it("never reads its own half-finished group as a decimal point", () => {
		expect(parseMoneyInput("1,1080", "en")).toBe(11080);
		expect(parseMoneyInput("110,8000", "en")).toBe(1108000);
		expect(parseMoneyInput("1.1080", "tr")).toBe(11080);
		expect(parseMoneyInput("110.8000", "tr")).toBe(1108000);
	});

	// The narrowing must not eat the rescue it sits next to: a separator that is
	// NOT the locale's grouping mark stays a decimal point however many digits
	// follow it. Four-decimal unit prices and the ru numpad dot both depend on
	// this, and both are already shipping.
	it("still reads a foreign or four-decimal separator as the decimal point", () => {
		expect(parseMoneyInput("1500000.5000", "ru")).toBe(1500000.5);
		expect(parseMoneyInput("4.4150", "en")).toBe(4.415);
		expect(parseMoneyInput("4,4150", "tr")).toBe(4.415);
	});
});

describe("moneySeparators — one locale table, not two", () => {
	// money.js maps tr to tr-TR (20.820,00) while MoneyInput hardcoded
	// `en ? en-US : ru-RU`, so a Turkish user read "20 820,00" inside the input
	// and "20.820,00" in the table beside it. Same page, two groupings.
	it("gives tr the dot grouping its tables already use", () => {
		expect(moneySeparators("tr")).toEqual({ group: ".", decimal: "," });
	});

	it("gives en the comma grouping", () => {
		expect(moneySeparators("en")).toEqual({ group: ",", decimal: "." });
	});

	it.each(["ru", "uz", "uzc"])("gives %s a space group and a comma decimal", (lang) => {
		const { group, decimal } = moneySeparators(lang);
		expect(norm(group)).toBe(" ");
		expect(decimal).toBe(",");
	});

	it("falls back to en for a language the SPA does not ship", () => {
		expect(moneySeparators("de")).toEqual(moneySeparators("en"));
	});
});
