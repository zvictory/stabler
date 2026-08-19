"""Seed the Chart of Accounts vocabulary into the five translation catalogues.

Why this exists as a script rather than a harvester run: the harvester scans for
literal `t("...")` calls, and account names are database values rendered through
a dynamic `t(account_name)` (see composables/accounts.js). They are invisible to
the regex, so they have to be written down once, here.

What is deliberately NOT in the list: counterparties, banks and a company's own
coinage — `MIKAS USD`, `Sansher RUB`, `TVZ ipak yo'li`, `PK` and their kin. A
name that identifies a party is not a word to be translated, and `t()` falls
through to the source string, so leaving them out is the whole mechanism.

Seven keys were already in the catalogues as UI labels — Cash, Equity, Expenses,
Salary, Sales, Service, VAT — and are left exactly as they were. `t()` is one
flat namespace, so re-translating them here for the accounting sense would have
silently changed those labels everywhere else in the app.

ru is filled because that is what was asked for. uz, uzc and tr get the keys
with empty targets, which is what a harvest would have produced: the gap stays
visible to the next translator and `t()` falls back to English until then.

Idempotent — appends only what is missing. Run:
    python3 stabler/translations/add_coa_translations.py
"""

import csv
import os

# (source, russian). Ordered as the chart reads: groups first, then the leaves.
COA = [
	# ── groups ────────────────────────────────────────────────────────────────
	("Application of Funds (Assets)", "Размещение средств (активы)"),
	("Source of Funds (Liabilities)", "Источники средств (обязательства)"),
	("Current Assets", "Оборотные активы"),
	("Current Liabilities", "Краткосрочные обязательства"),
	("Non-Current Liabilities", "Долгосрочные обязательства"),
	("Fixed Assets", "Основные средства"),
	("Investments", "Инвестиции"),
	("Bank Accounts", "Банковские счета"),
	("Cash In Hand", "Денежные средства в кассе"),
	("Accounts Receivable", "Дебиторская задолженность"),
	("Accounts Payable", "Кредиторская задолженность"),
	("Duties and Taxes", "Пошлины и налоги"),
	("Tax Assets", "Налоговые активы"),
	("Loans (Liabilities)", "Займы (обязательства)"),
	("Loans and Advances (Assets)", "Займы и авансы выданные"),
	("Securities and Deposits", "Ценные бумаги и депозиты"),
	("Stock Assets", "Товарно-материальные запасы"),
	("Stock Expenses", "Расходы по запасам"),
	("Stock Liabilities", "Обязательства по запасам"),
	("Temporary Accounts", "Временные счета"),
	("Income", "Доходы"),
	("Direct Income", "Прямые доходы"),
	("Indirect Income", "Косвенные доходы"),
	("Direct Expenses", "Прямые расходы"),
	("Indirect Expenses", "Косвенные расходы"),
	("RUB BANK", "Банк RUB"),
	("USD BANK", "Банк USD"),
	("UZS BANK", "Банк UZS"),
	("YUAN BANK", "Банк CNY"),
	# ── leaves ────────────────────────────────────────────────────────────────
	("Accrued Expenses", "Начисленные расходы"),
	("Accumulated Depreciation", "Накопленная амортизация"),
	("Administrative Expenses", "Административные расходы"),
	("Asset Received But Not Billed", "Актив получен, но счёт не выставлен"),
	("Bank Charges", "Банковские комиссии"),
	("Bank Overdraft Account", "Банковский овердрафт"),
	("Buildings", "Здания"),
	("CWIP Account", "Незавершённое строительство"),
	("Capital Equipment", "Капитальное оборудование"),
	("Capital Stock", "Уставный капитал"),
	("Commission on Sales", "Комиссия с продаж"),
	("Cost of Goods Sold", "Себестоимость продаж"),
	("Creditors", "Кредиторы"),
	("Customer Advances", "Авансы покупателей"),
	("Debtors", "Дебиторы"),
	("Depreciation", "Амортизация"),
	("Dividends Paid", "Выплаченные дивиденды"),
	("Earnest Money", "Задаток"),
	("Electronic Equipment", "Электронное оборудование"),
	("Employee Advances", "Авансы сотрудникам"),
	("Employee Benefits Obligation", "Обязательства по вознаграждениям работникам"),
	("Entertainment Expenses", "Представительские расходы"),
	("Exchange Gain/Loss", "Курсовые разницы"),
	("Expenses Included In Asset Valuation", "Расходы, включённые в стоимость актива"),
	("Expenses Included In Valuation", "Расходы, включённые в стоимость запасов"),
	("Freight and Forwarding Charges", "Транспортно-экспедиторские расходы"),
	("Furniture and Fixtures", "Мебель и оснащение"),
	("Gain/Loss on Asset Disposal", "Прибыль/убыток от выбытия активов"),
	("Impairment", "Обесценение"),
	("Interest Expense", "Процентные расходы"),
	("Interest Income", "Процентные доходы"),
	("Interest on Fixed Deposits", "Проценты по срочным депозитам"),
	("Kassa Som", "Касса (сум)"),
	("USD Kassa", "Касса (USD)"),
	("Legal Expenses", "Юридические расходы"),
	("Long-term Provisions", "Долгосрочные резервы"),
	("Marketing Expenses", "Маркетинговые расходы"),
	("Miscellaneous Expenses", "Прочие расходы"),
	("Office Equipment", "Офисное оборудование"),
	("Office Maintenance Expenses", "Расходы на содержание офиса"),
	("Office Rent", "Аренда офиса"),
	("Opening Balance Equity", "Капитал: входящее сальдо"),
	("Payroll Payable", "Задолженность по заработной плате"),
	("Plants and Machineries", "Машины и оборудование"),
	("Postal Expenses", "Почтовые расходы"),
	("Prepaid Expenses", "Расходы будущих периодов"),
	("Print and Stationery", "Печать и канцелярия"),
	("Retained Earnings", "Нераспределённая прибыль"),
	("Revaluation Surplus", "Прирост от переоценки"),
	("Round Off", "Округление"),
	("Sales Expenses", "Коммерческие расходы"),
	("Secured Loans", "Обеспеченные займы"),
	("Short-term Investments", "Краткосрочные инвестиции"),
	("Short-term Provisions", "Краткосрочные резервы"),
	("Software", "Программное обеспечение"),
	("Stock Adjustment", "Корректировка запасов"),
	("Stock In Hand", "Запасы на складе"),
	("Stock Received But Not Billed", "Запасы получены, но счёт не выставлен"),
	("Tax Expense", "Расход по налогу"),
	("Telephone Expenses", "Расходы на связь"),
	("Temporary Opening", "Временный счёт открытия"),
	("Travel Expenses", "Командировочные расходы"),
	("Unsecured Loans", "Необеспеченные займы"),
	("Utility Expenses", "Коммунальные расходы"),
	("Write Off", "Списание"),
]

# `account_type` values ERPNext ships as a fixed enum. They render as a badge on
# the chart and as the labels of the type dropdown, so they are labels like any
# other — only they were never wrapped in t() until now.
ACCOUNT_TYPES = [
	("Capital Work in Progress", "Незавершённое строительство"),
	("Chargeable", "Возмещаемые"),
	("Current Asset", "Оборотный актив"),
	("Current Liability", "Краткосрочное обязательство"),
	("Direct Expense", "Прямой расход"),
	("Expense Account", "Счёт расходов"),
	("Fixed Asset", "Основное средство"),
	("Income Account", "Счёт доходов"),
	("Indirect Expense", "Косвенный расход"),
	("Liability", "Обязательство"),
	("Payable", "Кредиторская задолженность"),
	("Receivable", "Дебиторская задолженность"),
	("Round Off for Opening", "Округление для открытия"),
	("Service Received But Not Billed", "Услуги получены, но счёт не выставлен"),
	("Stock", "Запасы"),
	("Tax", "Налог"),
	("Temporary", "Временный"),
	("Bank", "Банк"),
]

# New literals introduced alongside the translation layer, listed here because a
# harvest run needs a live bench and this script does not.
UI = [
	("No accounts yet", "Счетов пока нет"),
	(
		"Set up the chart of accounts for {company} to see it here.",
		"Настройте план счетов для {company}, чтобы увидеть его здесь.",
	),
]

PAIRS = COA + ACCOUNT_TYPES + UI
LANGS = ("en", "ru", "uz", "uzc", "tr")


def main():
	base_dir = os.path.dirname(__file__)
	for lang in LANGS:
		filepath = os.path.join(base_dir, f"{lang}.csv")
		if not os.path.exists(filepath):
			continue

		existing = set()
		with open(filepath, encoding="utf-8") as f:
			for row in csv.reader(f):
				if row:
					existing.add(row[0])

		# en mirrors the source, exactly as harvest.run() does. uz/uzc/tr get the
		# key with an empty target so the gap is visible rather than absent.
		new_rows = [
			(src, src if lang == "en" else (ru if lang == "ru" else ""))
			for src, ru in PAIRS
			if src not in existing
		]
		if not new_rows:
			print(f"{lang}.csv: nothing to add")
			continue
		with open(filepath, "a", encoding="utf-8", newline="") as f:
			# csv.writer defaults to CRLF however the file was opened; these
			# catalogues are LF and a mixed-ending row is the bug this guards.
			writer = csv.writer(f, lineterminator="\n")
			writer.writerows(new_rows)
		print(f"Added {len(new_rows)} translations to {lang}.csv")


if __name__ == "__main__":
	main()
