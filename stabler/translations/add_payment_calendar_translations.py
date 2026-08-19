"""Seed the payment-calendar strings into the five language CSVs.

`harvest.py` only sees literal `t("...")` calls, and this screen resolves several
of its labels dynamically — `t(row.kind)` for the eight kinds, `t(dt)` for the
document types the picker offers. Those never reach the harvester, so they are
listed here alongside the literal strings, following the same pattern as
`add_coa_translations.py`.

Russian is filled in; uz / uzc / tr are left empty on purpose, so `t()` falls
back to the English source until somebody translates them.

Idempotent: only missing sources are appended. Run with plain python — it needs
no bench:

    python stabler/translations/add_payment_calendar_translations.py
"""

from __future__ import annotations

import csv
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_LANGS = ("en", "ru", "uz", "uzc", "tr")

# source -> Russian. Everything the calendar renders, literal and dynamic alike.
STRINGS = {
	# Page identity
	"Payment Calendar": "Платёжный календарь",
	"Everyone enters their own plan. The calendar shows the days it lands on.": "Каждый вносит свой план. Календарь показывает, на какие дни он приходится.",
	"My plan": "Мой план",
	"Whole company": "Вся компания",
	"Click a day to plan on it": "Нажмите на день, чтобы внести план",
	"Nothing planned this month yet.": "В этом месяце пока ничего не запланировано.",
	# Kinds — resolved dynamically from the row, so invisible to the harvester.
	"Customer receipt": "Поступление от клиента",
	"Vendor payment": "Оплата поставщику",
	"Item purchase": "Закупка товара",
	"Other receipt": "Прочее поступление",
	"Other payment": "Прочая оплата",
	"Customer Receipt": "Поступление от клиента",
	"Vendor Payment": "Оплата поставщику",
	"Item Purchase": "Закупка товара",
	"Other Receipt": "Прочее поступление",
	"Other Payment": "Прочая оплата",
	# Confidence
	"Confidence": "Уверенность",
	"Committed — agreed, date is set": "Точно — согласовано, дата известна",
	"Expected — most likely": "Ожидается — скорее всего",
	"Tentative — not discussed yet": "Предварительно — ещё не обсуждалось",
	"A tentative receipt does not pay a committed salary — the three are summed apart.": "Предварительное поступление не оплатит точную зарплату — три уровня суммируются отдельно.",
	# Repeat
	"Repeat": "Повтор",
	"One time": "Один раз",
	"Every week ×4": "Каждую неделю ×4",
	"Every month ×3": "Каждый месяц ×3",
	"Every month ×6": "Каждый месяц ×6",
	"Every month ×12": "Каждый месяц ×12",
	# Money and direction
	"Incoming": "Поступления",
	"Outgoing": "Выплаты",
	"Heaviest day": "Самый тяжёлый день",
	# Form
	"What for": "За что",
	"New planned payment": "Новый плановый платёж",
	"Edit planned payment": "Изменить плановый платёж",
	"Add to plan": "Добавить в план",
	"The amount and date are read from the document.": "Сумма и дата берутся из документа.",
	"This screen does not pay anything. Money leaves through Payments, Kassa or Journal; a row is closed here by hand.": "Этот экран не проводит платежи. Деньги уходят через «Платежи», «Кассу» или «Журнал»; строка закрывается здесь вручную.",
	"Realized": "Исполнено",
	"Realized on": "Дата исполнения",
	# Manager view
	"Totals by planner": "Итоги по сотрудникам",
	"Visible to authorised roles only": "Видно только уполномоченным ролям",
	"Planned by": "Кто внёс план",
	"Rows": "Строк",
	# Errors
	"Failed to load the payment calendar.": "Не удалось загрузить платёжный календарь.",
	"Failed to save the plan.": "Не удалось сохранить план.",
	"Failed to delete the plan.": "Не удалось удалить план.",
	# Document types offered by the picker — resolved via t(dt).
	"Proforma Invoice": "Проформа-инвойс",
}


def _read(path: Path) -> dict[str, str]:
	rows: dict[str, str] = {}
	if not path.exists():
		return rows
	with path.open("r", encoding="utf-8", newline="") as fh:
		for row in csv.reader(fh):
			if len(row) >= 2 and row[0]:
				rows[row[0]] = row[1]
	return rows


def main() -> None:
	for lang in _LANGS:
		path = _DIR / f"{lang}.csv"
		existing = _read(path)
		missing = [s for s in STRINGS if s not in existing]
		if not missing:
			print(f"{lang}: nothing to add")
			continue
		with path.open("a", encoding="utf-8", newline="") as fh:
			writer = csv.writer(fh, lineterminator="\n")
			for source in missing:
				writer.writerow(
					[source, source if lang == "en" else (STRINGS[source] if lang == "ru" else "")]
				)
		print(f"{lang}: added {len(missing)}")


if __name__ == "__main__":
	main()
