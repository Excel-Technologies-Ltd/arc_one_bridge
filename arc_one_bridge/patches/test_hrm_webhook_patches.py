# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from arc_one_bridge.patches import delete_hrm_webhooks, disable_hrm_webhooks

BASE = "https://arc-one.test"


def make_webhook(path, doctype="Attendance", enabled=1):
	return frappe.get_doc(
		{
			"doctype": "Webhook",
			"webhook_doctype": doctype,
			"webhook_docevent": "on_update",
			"request_url": f"{BASE}{path}",
			"request_method": "POST",
			"request_structure": "Form URL-Encoded",
			"webhook_headers": [{"key": "Content-Type", "value": "application/json"}],
			"webhook_data": [{"fieldname": "name", "key": "name"}],
			"enabled": enabled,
		}
	).insert(ignore_permissions=True)


def log_disable_patch(ran_at):
	frappe.db.delete("Patch Log", {"patch": delete_hrm_webhooks.DISABLE_PATCH})
	log = frappe.get_doc({"doctype": "Patch Log", "patch": delete_hrm_webhooks.DISABLE_PATCH}).insert(
		ignore_permissions=True
	)
	frappe.db.set_value("Patch Log", log.name, "creation", ran_at, update_modified=False)


class TestHrmWebhookPatches(FrappeTestCase):
	def setUp(self):
		patcher = patch.dict(frappe.conf, {"arc_one_api_base_url": BASE})
		patcher.start()
		self.addCleanup(patcher.stop)
		self.hrm = make_webhook("/api/v1/hrm/attendance/on-create")
		self.kept = make_webhook("/api/v1/user-webhooks/on-create", doctype="User")
		frappe.db.delete("Patch Log", {"patch": delete_hrm_webhooks.DISABLE_PATCH})

	def enabled(self, webhook):
		return frappe.db.get_value("Webhook", webhook.name, "enabled")

	def test_the_disable_patch_turns_off_the_hrm_webhooks_only(self):
		disable_hrm_webhooks.execute()

		self.assertEqual(self.enabled(self.hrm), 0)
		self.assertEqual(self.enabled(self.kept), 1)

	def test_the_delete_patch_waits_for_the_disable_patch(self):
		delete_hrm_webhooks.execute()

		self.assertTrue(frappe.db.exists("Webhook", self.hrm.name))

	def test_the_delete_patch_waits_out_the_fourteen_days(self):
		disable_hrm_webhooks.execute()
		log_disable_patch(now_datetime() - timedelta(days=delete_hrm_webhooks.MIN_DAYS_DISABLED - 1))

		delete_hrm_webhooks.execute()

		self.assertTrue(frappe.db.exists("Webhook", self.hrm.name))

	def test_the_delete_patch_removes_them_once_the_wait_is_over(self):
		disable_hrm_webhooks.execute()
		log_disable_patch(now_datetime() - timedelta(days=delete_hrm_webhooks.MIN_DAYS_DISABLED + 1))

		delete_hrm_webhooks.execute()

		self.assertFalse(frappe.db.exists("Webhook", self.hrm.name))
		self.assertTrue(frappe.db.exists("Webhook", self.kept.name))

	def test_the_delete_patch_keeps_a_webhook_somebody_re_enabled(self):
		log_disable_patch(now_datetime() - timedelta(days=delete_hrm_webhooks.MIN_DAYS_DISABLED + 1))

		delete_hrm_webhooks.execute()

		self.assertTrue(frappe.db.exists("Webhook", self.hrm.name))
