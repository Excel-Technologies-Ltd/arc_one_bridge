# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from arc_one_bridge.tasks import invoice_status

TASK = "arc_one_bridge.tasks.invoice_status"


class TestRecordOverdueInvoices(FrappeTestCase):
	def setUp(self):
		frappe.cache().delete_value(invoice_status.LAST_FOLLOWED_KEY)
		self.recorded = []
		patcher = patch(
			f"{TASK}.ArcOneChangeLog.record",
			side_effect=lambda doctype, name, event: self.recorded.append((doctype, name, event)),
		)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(frappe.cache().delete_value, invoice_status.LAST_FOLLOWED_KEY)

	def _run(self, last_run, overdue=("SINV-1", "SINV-2"), tracked=True):
		with patch(f"{TASK}.is_tracked", return_value=tracked), patch(
			f"{TASK}._last_completed_run", return_value=last_run
		), patch(f"{TASK}.recently_overdue_invoices", return_value=list(overdue)):
			invoice_status.record_overdue_invoices()

	def test_records_each_overdue_invoice_once_per_erpnext_run(self):
		run = datetime(2026, 10, 8, 0, 5)
		self._run(run)
		self._run(run)

		self.assertEqual(
			self.recorded,
			[("Sales Invoice", "SINV-1", "update"), ("Sales Invoice", "SINV-2", "update")],
		)

	def test_follows_the_next_run_again(self):
		self._run(datetime(2026, 10, 7, 0, 5), overdue=("SINV-1",))
		self._run(datetime(2026, 10, 8, 0, 5), overdue=("SINV-2",))

		self.assertEqual([name for _, name, _ in self.recorded], ["SINV-1", "SINV-2"])

	def test_does_nothing_before_the_erpnext_job_has_completed(self):
		self._run(None)
		self.assertEqual(self.recorded, [])

	def test_does_nothing_when_invoices_are_not_tracked(self):
		self._run(datetime(2026, 10, 8, 0, 5), tracked=False)
		self.assertEqual(self.recorded, [])
