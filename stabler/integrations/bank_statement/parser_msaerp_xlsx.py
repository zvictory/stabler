import openpyxl
import io
import hashlib
from datetime import datetime, date

DEPOSIT = "deposit"
WITHDRAWAL = "withdrawal"

def is_msaerp_xlsx(raw: bytes) -> bool:
	# Excel signature
	return raw.startswith(b"PK\x03\x04")

def parse_statement_bytes(raw: bytes, our_account: str | None = None) -> dict:
	wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
	ws = wb.active
	
	rows_iter = ws.iter_rows(values_only=True)
	header = next(rows_iter, None)
	if not header:
		raise ValueError("Excel file is empty")

	normalized = [(str(c).strip().lower() if c is not None else "") for c in header]
	
	col = {}
	for key, synonyms in {
		"date": ("date", "tarih", "gün"),
		"debit": ("debit", "debit (withdrawal)", "borç", "withdrawal"),
		"credit": ("credit", "credit (deposit)", "alacak", "deposit"),
		"description": ("description", "açıklama", "remark", "notes"),
		"reference": ("reference", "reference number", "ref", "fiş no", "belge no"),
	}.items():
		for syn in synonyms:
			if syn in normalized:
				col[key] = normalized.index(syn)
				break

	if "date" not in col or "description" not in col or ("debit" not in col and "credit" not in col):
		# Fallback to standard columns
		col = {"date": 0, "debit": 1, "credit": 2, "description": 3, "reference": 4}

	def pick(row: tuple, key: str):
		i = col.get(key)
		if i is None or i >= len(row):
			return None
		return row[i]

	rows = []
	dates = []

	for row_num, row in enumerate(rows_iter, start=2):
		if not row or all(c is None or c == "" for c in row):
			continue

		raw_date = pick(row, "date")
		if not raw_date:
			continue

		parsed_date = None
		if isinstance(raw_date, (datetime, date)):
			parsed_date = raw_date if isinstance(raw_date, date) else raw_date.date()
		else:
			s = str(raw_date).strip()
			for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
				try:
					parsed_date = datetime.strptime(s, fmt).date()
					break
				except ValueError:
					continue

		if not parsed_date:
			continue

		dates.append(parsed_date)

		def to_float(val):
			if val is None or val == "":
				return 0.0
			try:
				return abs(float(str(val).replace("\xa0", "").replace(" ", "").replace(",", "")))
			except ValueError:
				return 0.0

		debit = to_float(pick(row, "debit"))
		credit = to_float(pick(row, "credit"))

		amount = max(debit, credit)
		direction = DEPOSIT if credit > debit else WITHDRAWAL

		ref = str(pick(row, "reference") or "").strip()
		desc = str(pick(row, "description") or "").strip()

		raw_key = "|".join([
			parsed_date.isoformat(),
			f"{round(amount, 2)}",
			direction,
			ref,
			desc[:30]
		])
		dedupe_key = "MSA-EXC-" + hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:12]

		rows.append({
			"date": parsed_date.isoformat(),
			"amount": amount,
			"direction": direction,
			"deposit": amount if direction == DEPOSIT else 0.0,
			"withdrawal": amount if direction == WITHDRAWAL else 0.0,
			"reference_number": ref,
			"description": desc,
			"dedupe_key": dedupe_key,
			"doc_type": "Excel Import"
		})

	dates.sort()
	period_from = dates[0].isoformat() if dates else None
	period_to = dates[-1].isoformat() if dates else None

	return {
		"account": our_account or "Excel Account",
		"period_from": period_from,
		"period_to": period_to,
		"rows": rows,
		"count": len(rows),
	}
