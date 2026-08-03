"""Customer creation must never default to a non-transactional group node."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from stabler.api import sales


class TestDefaultCustomerGroup(unittest.TestCase):
	def test_uses_configured_leaf_group(self):
		db = Mock()
		db.get_single_value.return_value = "Commercial"
		db.get_value.return_value = 0
		with patch.object(sales, "frappe", SimpleNamespace(db=db)):
			self.assertEqual(sales._default_customer_group(), "Commercial")
			db.get_value.assert_called_once_with("Customer Group", "Commercial", "is_group")

	def test_root_default_falls_back_to_first_leaf(self):
		db = Mock()
		db.get_single_value.return_value = "All Customer Groups"
		db.get_value.side_effect = [1, "Commercial"]
		with patch.object(sales, "frappe", SimpleNamespace(db=db)):
			self.assertEqual(sales._default_customer_group(), "Commercial")
			self.assertEqual(
				db.get_value.call_args_list[1].args,
				("Customer Group", {"is_group": 0}, "name"),
			)
			self.assertEqual(db.get_value.call_args_list[1].kwargs, {"order_by": "name asc"})


if __name__ == "__main__":
	unittest.main()
