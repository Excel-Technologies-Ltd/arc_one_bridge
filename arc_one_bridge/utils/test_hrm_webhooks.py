# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from arc_one_bridge.utils import hrm_webhooks

BASE = "https://arc-one.test"
OTHER_BASE = "https://iou.arc-one.test"


def make_webhook(path, doctype="Attendance", base=BASE, event="on_update"):
	return frappe.get_doc(
		{
			"doctype": "Webhook",
			"webhook_doctype": doctype,
			"webhook_docevent": event,
			"request_url": f"{base}{path}",
			"request_method": "POST",
			"request_structure": "Form URL-Encoded",
			"webhook_headers": [{"key": "Content-Type", "value": "application/json"}],
			"webhook_data": [{"fieldname": "name", "key": "name"}],
			"enabled": 1,
		}
	).insert(ignore_permissions=True)


def enabled(webhook):
	return frappe.db.get_value("Webhook", webhook.name, "enabled")


class TestHrmWebhooks(FrappeTestCase):
	def setUp(self):
		patcher = patch.dict(frappe.conf, {"arc_one_api_base_url": BASE})
		patcher.start()
		self.addCleanup(patcher.stop)
		self.hrm = [
			make_webhook("/api/v1/hrm/attendance/on-create"),
			make_webhook("/api/v1/hrm/employee-checkin/on-delete", "Employee Checkin", event="on_trash"),
			make_webhook("/api/v1/hrm/holiday-list/on-create", "Holiday List"),
			make_webhook("/api/v1/shifts-webhook/on-update", "Shift Type"),
			make_webhook("/api/v1/attendance-request-webhook/on-update", "Attendance Request"),
			make_webhook("/api/v1/leave-application/on-create", "Leave Application"),
			make_webhook("/api/v1/hrm/leave-application/on-delete", "Leave Application", event="on_trash"),
		]
		self.kept = [
			make_webhook("/api/v1/user-webhooks/on-create", "User"),
			make_webhook("/api/v1/employee-webhook/on-update", "Employee"),
			make_webhook("/api/v1/hrm/attendance/on-create", base=OTHER_BASE),
		]

	def test_disable_turns_off_only_this_apis_hrm_webhooks(self):
		hrm_webhooks.disable()

		for webhook in self.hrm:
			self.assertEqual(enabled(webhook), 0, webhook.request_url)
		for webhook in self.kept:
			self.assertEqual(enabled(webhook), 1, webhook.request_url)

	def test_enable_reverses_disable(self):
		hrm_webhooks.disable()
		hrm_webhooks.enable()

		for webhook in self.hrm:
			self.assertEqual(enabled(webhook), 1, webhook.request_url)

	def test_delete_removes_only_disabled_hrm_webhooks(self):
		frappe.db.set_value("Webhook", self.hrm[0].name, "enabled", 0)

		result = hrm_webhooks.delete()

		self.assertEqual([row[0] for row in result["webhooks"]], [self.hrm[0].name])
		self.assertFalse(frappe.db.exists("Webhook", self.hrm[0].name))
		for webhook in self.hrm[1:] + self.kept:
			self.assertTrue(frappe.db.exists("Webhook", webhook.name), webhook.request_url)

	def test_dry_run_changes_nothing(self):
		result = hrm_webhooks.disable(dry_run=True)

		self.assertEqual(len(result["webhooks"]), len(self.hrm))
		for webhook in self.hrm:
			self.assertEqual(enabled(webhook), 1, webhook.request_url)

	def test_skips_without_the_api_address(self):
		# Said, not raised: these run as patches, and a patch must not stop a migrate.
		with patch.dict(frappe.conf, {"arc_one_api_base_url": ""}):
			result = hrm_webhooks.disable()

		self.assertIn("arc_one_api_base_url", result["skipped"])
		self.assertEqual(result["webhooks"], [])
		for webhook in self.hrm:
			self.assertEqual(enabled(webhook), 1, webhook.request_url)
