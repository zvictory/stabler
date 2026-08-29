"""What the Work Order register must hand back, and why each column is load-bearing.

The register's SELECT feeds three screens — the list, the shift strip and the
shop-floor board — and a column dropped from it does not fail anywhere. It shows
up as a screen that is quietly wrong: the board's «Завершён · смена» column
filters on `actual_end_date`, so without that column every finished order looks
like it never finished and the shift's output column is permanently empty. There
is no error, no blank, no zero that looks unusual — just a column that says 0 on
a day the factory finished two orders.

Measured on anjan 2026-08-29: 3 757 of 3 799 orders carry `actual_end_date`, so
the field is populated in production and the column is worth reading.

Read out of the source rather than run: the question here is which columns the
statement names, and that is answerable without a database.
`test_wo_role_scoping_integration` keeps proving the query runs against real
columns.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_wo_register_columns -v
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

API = Path(__file__).resolve().parent.parent / "api" / "manufacturing.py"


def register_select() -> str:
	"""The SELECT inside `list_work_orders`, up to its FROM."""
	src = API.read_text(encoding="utf-8")
	start = src.index("def list_work_orders(")
	body = src[start : src.index("\ndef ", start + 1)]
	return re.search(r"SELECT (.*?)\n\t\tFROM", body, re.S).group(1)


class TestTheRegisterHandsBackWhatTheBoardReads(unittest.TestCase):
	def test_the_finish_time_is_selected(self):
		"""The board's shift window is built on it, and its absence is silent —
		every finished order simply stops matching the shift and the column reads
		0 on a day that produced."""
		self.assertIn("actual_end_date", register_select())

	def test_the_columns_the_board_derives_its_state_from_are_selected(self):
		"""`boardColumn` decides a card's column from exactly these. A missing one
		does not throw either: `Number(undefined) || 0` is 0, so an order with
		material already issued would draw as untouched."""
		select = register_select()
		for column in ("docstatus", "status", "produced_qty", "material_transferred_for_manufacturing"):
			self.assertIn(column, select)


if __name__ == "__main__":
	unittest.main()
