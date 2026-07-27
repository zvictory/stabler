"""Standalone shadow ledger store for KassaBot v2 — a SEPARATE SQLite file.

This is NOT the ERPNext/Frappe database and NOT a doctype. The bot writes signed
per-kassa deltas here; the mini app reads balances. It never touches accounting
(no GL, no Journal Entry). This module is frappe-free and unit-testable — the
thin wrapper (shadow.py) only supplies the file path.

Data model
- shadow_entry : one kassir action (op + counterparty + purpose + rate + raw_text
  + parsed_json). One action may move money into several kassas.
- shadow_delta : signed amount per kassa for an entry (kirim +, chiqim −, konv/k2k
  legs already signed by the writer). Balance = Σ deltas (+ opening).
- shadow_opening : manually-entered opening balance per (company, date, kassa).

Balance(kassa, date) = opening(kassa, date) + Σ shadow_delta(kassa, date).
"""

from __future__ import annotations

import json
import sqlite3
import time

KASSAS = ("nakit", "pk", "usd")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_entry(
  id TEXT PRIMARY KEY, company TEXT, kassir TEXT, date TEXT, ts INTEGER,
  op TEXT, counterparty TEXT, purpose TEXT, rate REAL,
  raw_text TEXT, parsed_json TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS shadow_delta(
  entry_id TEXT, company TEXT, date TEXT, kassa TEXT, delta REAL
);
CREATE TABLE IF NOT EXISTS shadow_opening(
  company TEXT, date TEXT, kassa TEXT, amount REAL,
  PRIMARY KEY(company, date, kassa)
);
CREATE INDEX IF NOT EXISTS ix_delta_cdk ON shadow_delta(company, date, kassa);
CREATE INDEX IF NOT EXISTS ix_entry_cd ON shadow_entry(company, date);
"""


def connect(path: str) -> sqlite3.Connection:
	con = sqlite3.connect(path)
	con.executescript(_SCHEMA)
	return con


def _today() -> str:
	return time.strftime("%Y-%m-%d")


def add_entry(
	path,
	*,
	company,
	kassir,
	op,
	deltas,
	date=None,
	counterparty=None,
	purpose=None,
	rate=None,
	raw_text=None,
	parsed=None,
	ts=None,
) -> str:
	"""Insert one shadow action + its signed per-kassa deltas. Returns entry id.

	`deltas`: list of {"kassa": "nakit|pk|usd", "delta": <signed float>}.
	"""
	ts = int(ts if ts is not None else time.time() * 1000)
	date = date or _today()
	eid = "kse%d%03d" % (ts, int((time.time() % 1) * 1000))
	con = connect(path)
	try:
		con.execute(
			"INSERT INTO shadow_entry VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
			(
				eid,
				company,
				str(kassir),
				date,
				ts,
				op,
				counterparty,
				purpose,
				(float(rate) if rate is not None else None),
				raw_text,
				json.dumps(parsed or {}, ensure_ascii=False),
				time.strftime("%Y-%m-%d %H:%M:%S"),
			),
		)
		for d in deltas or []:
			con.execute(
				"INSERT INTO shadow_delta(entry_id,company,date,kassa,delta) VALUES(?,?,?,?,?)",
				(eid, company, date, d["kassa"], float(d["delta"])),
			)
		con.commit()
	finally:
		con.close()
	return eid


def delete_entry(path, eid, company) -> None:
	con = connect(path)
	try:
		con.execute("DELETE FROM shadow_delta WHERE entry_id=? AND company=?", (eid, company))
		con.execute("DELETE FROM shadow_entry WHERE id=? AND company=?", (eid, company))
		con.commit()
	finally:
		con.close()


def set_opening(path, company, date, kassa, amount) -> None:
	con = connect(path)
	try:
		con.execute(
			"INSERT INTO shadow_opening(company,date,kassa,amount) VALUES(?,?,?,?) "
			"ON CONFLICT(company,date,kassa) DO UPDATE SET amount=excluded.amount",
			(company, date, kassa, float(amount)),
		)
		con.commit()
	finally:
		con.close()


def get_openings(path, company, date) -> dict:
	con = connect(path)
	try:
		rows = con.execute(
			"SELECT kassa, amount FROM shadow_opening WHERE company=? AND date=?",
			(company, date),
		).fetchall()
	finally:
		con.close()
	return {k: float(a) for k, a in rows}


def balances(path, company, date) -> dict:
	"""{'nakit':..,'pk':..,'usd':..} = opening + Σ deltas for the day."""
	con = connect(path)
	try:
		op = dict(
			con.execute(
				"SELECT kassa, amount FROM shadow_opening WHERE company=? AND date=?", (company, date)
			).fetchall()
		)
		deltas = con.execute(
			"SELECT kassa, COALESCE(SUM(delta),0) FROM shadow_delta "
			"WHERE company=? AND date=? GROUP BY kassa",
			(company, date),
		).fetchall()
	finally:
		con.close()
	b = {k: float(op.get(k, 0.0)) for k in KASSAS}
	for k, s in deltas:
		b[k] = b.get(k, 0.0) + float(s)
	return b


def list_entries(path, company, date) -> list:
	con = connect(path)
	try:
		rows = con.execute(
			"SELECT id,ts,op,counterparty,purpose,rate,raw_text,parsed_json "
			"FROM shadow_entry WHERE company=? AND date=? ORDER BY ts DESC",
			(company, date),
		).fetchall()
		out = []
		for r in rows:
			legs = con.execute("SELECT kassa, delta FROM shadow_delta WHERE entry_id=?", (r[0],)).fetchall()
			out.append(
				{
					"id": r[0],
					"ts": r[1],
					"op": r[2],
					"counterparty": r[3],
					"purpose": r[4],
					"rate": r[5],
					"raw_text": r[6],
					"parsed": json.loads(r[7] or "{}"),
					"legs": [{"kassa": k, "delta": float(d)} for k, d in legs],
				}
			)
	finally:
		con.close()
	return out
