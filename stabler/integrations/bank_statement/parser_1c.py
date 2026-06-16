# This module parses a Russian-language format; the Cyrillic keys it matches on
# (which ruff flags as Latin-confusable) are required and intentional. The
# RUF001/RUF003 confusable lints are disabled for this dir in pyproject.toml.
"""Parser for the 1C ClientBank Exchange statement format (`1CClientBankExchange`).

This is the de-facto bank-statement exchange format across the CIS, including
Uzbekistan — most bank-client / internet-bank apps export it. The file is a flat
``Ключ=Значение`` (key=value) text, usually Windows-1251 encoded, structured as:

    1CClientBankExchange
    ВерсияФормата=1.03
    Кодировка=Windows
    ДатаНачала=01.01.2026
    ДатаКонца=31.01.2026
    РасчСчет=20208000900000000001          <- the statement's own account
    СекцияРасчСчет
        ...account opening/closing balances...
    КонецРасчСчет
    СекцияДокумент=Платежное поручение
        Номер=123
        Дата=15.01.2026
        Сумма=5000000.00
        ПлательщикСчет=...   ПлательщикИНН=...   Плательщик=...
        ПолучательСчет=...   ПолучательИНН=...   Получатель=...
        НазначениеПлатежа=Оплата за ...
        ДатаСписано=15.01.2026     (debited)  / ДатаПоступило=...  (credited)
    КонецДокумента
    КонецФайла

Everything here is pure (bytes/text in, dicts out) so it is unit-testable with
no bench. The Frappe layer (``import_api``) turns normalized rows into
``Bank Transaction`` documents.
"""
from __future__ import annotations

# Direction of a line relative to the statement's own account.
DEPOSIT = "deposit"
WITHDRAWAL = "withdrawal"


# --------------------------------------------------------------------------- #
# Encoding
# --------------------------------------------------------------------------- #
def detect_encoding(raw: bytes) -> str:
	"""Read the ``Кодировка=`` header to choose a codec; default to cp1251.

	The header itself is ASCII-safe, so we can peek before decoding the body.
	1C uses "Windows" (cp1251), "DOS" (cp866) or "UTF-8".
	"""
	head = raw[:512].decode("ascii", errors="ignore").lower()
	if "кодировка" in raw[:512].decode("cp1251", errors="ignore").lower():
		line = raw[:512].decode("cp1251", errors="ignore").lower()
		if "utf-8" in line or "utf8" in line:
			return "utf-8"
		if "dos" in line or "866" in line:
			return "cp866"
		if "windows" in line or "1251" in line:
			return "cp1251"
	if "utf-8" in head or "utf8" in head:
		return "utf-8"
	return "cp1251"


def decode_statement(raw: bytes) -> str:
	"""Decode raw statement bytes to text using the declared encoding."""
	enc = detect_encoding(raw)
	try:
		return raw.decode(enc)
	except (UnicodeDecodeError, LookupError):
		return raw.decode("cp1251", errors="replace")


# --------------------------------------------------------------------------- #
# Parse
# --------------------------------------------------------------------------- #
def is_1c_exchange(text: str) -> bool:
	"""Cheap sniff: does this look like a 1C ClientBank Exchange file?"""
	return text.lstrip().startswith("1CClientBankExchange")


def parse_1c_exchange(text: str) -> dict:
	"""Parse the text into {header, accounts, documents}.

	header: dict of top-level key→value.
	accounts: list of СекцияРасчСчет blocks (dicts).
	documents: list of СекцияДокумент blocks (dicts, plus ``_type``).
	"""
	header: dict[str, str] = {}
	accounts: list[dict] = []
	documents: list[dict] = []

	current: dict | None = None
	mode: str | None = None  # "account" | "document" | None

	for raw_line in text.splitlines():
		line = raw_line.strip()
		if not line or line in ("1CClientBankExchange", "КонецФайла"):
			continue

		if line == "СекцияРасчСчет":
			current, mode = {}, "account"
			continue
		if line == "КонецРасчСчет":
			if current is not None:
				accounts.append(current)
			current, mode = None, None
			continue
		if line.startswith("СекцияДокумент"):
			current, mode = {}, "document"
			# "СекцияДокумент=Платежное поручение" → capture the doc type.
			if "=" in line:
				current["_type"] = line.split("=", 1)[1].strip()
			continue
		if line == "КонецДокумента":
			if current is not None:
				documents.append(current)
			current, mode = None, None
			continue

		if "=" not in line:
			continue
		key, value = line.split("=", 1)
		key, value = key.strip(), value.strip()
		if mode is None:
			header[key] = value
		elif current is not None:
			current[key] = value

	return {"header": header, "accounts": accounts, "documents": documents}


# --------------------------------------------------------------------------- #
# Normalize one statement's own account into bank-line rows
# --------------------------------------------------------------------------- #
def _parse_date(value: str | None) -> str | None:
	"""dd.mm.yyyy → yyyy-mm-dd. Returns None if unparseable/empty."""
	if not value:
		return None
	v = value.strip()
	for sep in (".", "/", "-"):
		if sep in v:
			parts = v.split(sep)
			if len(parts) == 3 and len(parts[0]) <= 2:
				d, m, y = parts
				if len(y) == 4 and d.isdigit() and m.isdigit() and y.isdigit():
					return f"{y}-{int(m):02d}-{int(d):02d}"
			# Already ISO (yyyy-mm-dd)?
			if len(parts) == 3 and len(parts[0]) == 4:
				y, m, d = parts
				if y.isdigit() and m.isdigit() and d.isdigit():
					return f"{y}-{int(m):02d}-{int(d):02d}"
			break
	return None


def _parse_amount(value: str | None) -> float:
	"""Parse '5000000.00' or '5 000 000,00' → float. Returns 0.0 on failure."""
	if not value:
		return 0.0
	v = value.strip().replace("\xa0", "").replace(" ", "")
	# If both separators present, the last one is the decimal separator.
	if "," in v and "." in v:
		if v.rfind(",") > v.rfind("."):
			v = v.replace(".", "").replace(",", ".")
		else:
			v = v.replace(",", "")
	elif "," in v:
		v = v.replace(",", ".")
	try:
		return float(v)
	except ValueError:
		return 0.0


def statement_account(parsed: dict) -> str | None:
	"""The РасчСчет the statement belongs to (header, else first account block)."""
	acct = parsed.get("header", {}).get("РасчСчет")
	if acct:
		return acct.strip()
	for a in parsed.get("accounts", []):
		if a.get("РасчСчет"):
			return a["РасчСчет"].strip()
	return None


def _direction(doc: dict, our_account: str | None) -> str | None:
	"""Is this line a deposit or withdrawal for our_account?

	Primary signal: which side (payer/receiver) carries our account number.
	Fallback: ДатаСписано (debited) → withdrawal; ДатаПоступило → deposit.
	"""
	payer = (doc.get("ПлательщикСчет") or doc.get("Плательщик1Счет") or "").strip()
	receiver = (doc.get("ПолучательСчет") or doc.get("Получатель1Счет") or "").strip()
	if our_account:
		if payer and payer == our_account:
			return WITHDRAWAL
		if receiver and receiver == our_account:
			return DEPOSIT
	if doc.get("ДатаСписано"):
		return WITHDRAWAL
	if doc.get("ДатаПоступило"):
		return DEPOSIT
	return None


def normalize_rows(parsed: dict, our_account: str | None = None) -> list[dict]:
	"""Turn parsed documents into normalized bank-line rows for our_account.

	Each row: date, amount, direction, deposit, withdrawal, reference_number,
	description, counterparty_name, counterparty_inn, counterparty_account,
	bank_code, doc_type, dedupe_key.
	"""
	if our_account is None:
		our_account = statement_account(parsed)

	rows: list[dict] = []
	for doc in parsed.get("documents", []):
		direction = _direction(doc, our_account)
		amount = _parse_amount(doc.get("Сумма"))
		date = _parse_date(doc.get("Дата") or doc.get("ДатаСписано") or doc.get("ДатаПоступило"))

		# Counterparty is the *other* side of the transaction.
		if direction == WITHDRAWAL:
			cp_name = doc.get("Получатель")
			cp_inn = doc.get("ПолучательИНН")
			cp_acc = doc.get("ПолучательСчет")
			bank_code = doc.get("ПолучательБИК") or doc.get("ПолучательМФО")
		else:
			cp_name = doc.get("Плательщик")
			cp_inn = doc.get("ПлательщикИНН")
			cp_acc = doc.get("ПлательщикСчет")
			bank_code = doc.get("ПлательщикБИК") or doc.get("ПлательщикМФО")

		ref = (doc.get("Номер") or "").strip()
		row = {
			"date": date,
			"amount": amount,
			"direction": direction,
			"deposit": amount if direction == DEPOSIT else 0.0,
			"withdrawal": amount if direction == WITHDRAWAL else 0.0,
			"reference_number": ref,
			"description": (doc.get("НазначениеПлатежа") or "").strip(),
			"counterparty_name": (cp_name or "").strip(),
			"counterparty_inn": (cp_inn or "").strip(),
			"counterparty_account": (cp_acc or "").strip(),
			"bank_code": (bank_code or "").strip(),
			"doc_type": doc.get("_type", ""),
		}
		row["dedupe_key"] = dedupe_key(row)
		rows.append(row)
	return rows


def dedupe_key(row: dict) -> str:
	"""Stable identity for a bank line, so re-importing a statement is safe."""
	return "|".join(
		[
			str(row.get("date") or ""),
			f"{_round2(row.get('amount'))}",
			str(row.get("direction") or ""),
			str(row.get("reference_number") or ""),
			str(row.get("counterparty_account") or ""),
		]
	)


def _round2(n) -> float:
	try:
		return round(float(n), 2)
	except (TypeError, ValueError):
		return 0.0


def parse_statement_bytes(raw: bytes, our_account: str | None = None) -> dict:
	"""End-to-end: bytes → {account, period, rows}. Pure except for decoding."""
	text = decode_statement(raw)
	parsed = parse_1c_exchange(text)
	acct = our_account or statement_account(parsed)
	rows = normalize_rows(parsed, acct)
	return {
		"account": acct,
		"period_from": _parse_date(parsed["header"].get("ДатаНачала")),
		"period_to": _parse_date(parsed["header"].get("ДатаКонца")),
		"rows": rows,
		"count": len(rows),
	}
