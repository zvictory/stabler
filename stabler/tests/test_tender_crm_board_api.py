import unittest
import os
import ast

class TestTenderCrmBoardApiSource(unittest.TestCase):
	def test_api_defines_crm_board_and_move_deal_stage(self):
		filepath = os.path.join(
			os.path.dirname(__file__), "..", "api", "tender.py"
		)
		with open(filepath, "r", encoding="utf-8") as f:
			tree = ast.parse(f.read(), filename=filepath)

		funcs = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
		self.assertIn("crm_board", funcs)
		self.assertIn("move_deal_stage", funcs)
