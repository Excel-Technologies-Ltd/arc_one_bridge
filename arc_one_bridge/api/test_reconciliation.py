# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from arc_one_bridge.api import reconciliation

MODULE = "arc_one_bridge.api.reconciliation"


class TestInvoiceSummary(FrappeTestCase):
	def _summary(self, from_date="1900-01-01", to_date="2999-12-31", tracked=True):
		with patch(f"{MODULE}.require_sync_role"), patch(f"{MODULE}.is_tracked", return_value=tracked):
			return reconciliation.invoice_summary(from_date, to_date)

	def test_counts_match_the_table_per_month_and_status(self):
		summary = self._summary()
		expected = frappe.db.sql(
			"""select date_format(posting_date, '%Y-%m') as month, status, count(*) as count
			from `tabSales Invoice` group by month, status""",
			as_dict=True,
		)

		self.assertEqual(
			sorted((row["month"], row["status"], row["count"]) for row in summary["months"]),
			sorted((row.month, row.status, row["count"]) for row in expected),
		)
		self.assertEqual(
			summary["first_date"],
			str(frappe.db.sql("select min(posting_date) from `tabSales Invoice`")[0][0] or "") or None,
		)

	def test_only_the_requested_dates_are_counted(self):
		self.assertEqual(self._summary("1900-01-01", "1900-12-31")["months"], [])

	def test_refused_when_invoices_are_not_replicated(self):
		with self.assertRaises(frappe.PermissionError):
			self._summary(tracked=False)
