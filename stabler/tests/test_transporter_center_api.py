import ast
import os
import unittest


class TestTransporterCenterApiSource(unittest.TestCase):
	def test_api_defines_transporter_dashboard_and_save_container_cost(self):
		filepath = os.path.join(os.path.dirname(__file__), "..", "api", "imports.py")
		with open(filepath, encoding="utf-8") as f:
			tree = ast.parse(f.read(), filename=filepath)

		funcs = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
		self.assertIn("transporter_dashboard", funcs)
		self.assertIn("save_container_transport_cost", funcs)


if __name__ == "__main__":
	unittest.main()
