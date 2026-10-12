# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from erpnext.accounts.utils import get_balance_on
from frappe.tests.utils import FrappeTestCase

from arc_one_bridge.api.balances import customer_balances


class TestCustomerBalances(FrappeTestCase):
	def _customers(self):
		with_entries = frappe.db.sql(
			"""select distinct party from `tabGL Entry` where party_type = 'Customer' limit 20""", pluck=True
		)
		without = frappe.get_all("Customer", pluck="name", limit=5)
		return list(dict.fromkeys([*with_entries, *without]))

	def test_matches_get_balance_on_for_every_customer(self):
		customers = self._customers()
		date = frappe.utils.nowdate()

		balances = customer_balances(customers, date)

		self.assertEqual(set(balances), set(customers))
		for customer in customers:
			self.assertAlmostEqual(
				balances[customer], get_balance_on(date=date, party_type="Customer", party=customer), places=6
			)

	def test_a_date_before_any_fiscal_year_has_no_balance(self):
		customers = self._customers()
		self.assertTrue(all(balance == 0 for balance in customer_balances(customers, "1900-01-01").values()))

	def test_accepts_the_list_as_json_and_an_empty_one(self):
		self.assertEqual(customer_balances("[]"), {})
		customers = self._customers()[:2]
		self.assertEqual(set(customer_balances(frappe.as_json(customers))), set(customers))
