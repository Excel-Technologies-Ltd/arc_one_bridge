# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from arc_one_bridge.patches import delete_sales_webhooks

BASE = "https://arc-one.test"


def make_webhook(path, module=None, doctype="Customer"):
	headers = [{"key": "Content-Type", "value": "application/json"}]
	if module:
		headers.append({"key": "x-module", "value": module})
	return frappe.get_doc(
		{
			"doctype": "Webhook",
			"webhook_doctype": doctype,
			"webhook_docevent": "on_update",
			"request_url": f"{BASE}{path}on-update",
			"request_method": "POST",
			"request_structure": "Form URL-Encoded",
			"webhook_headers": headers,
			"webhook_data": [{"fieldname": "name", "key": "name"}],
		}
	).insert(ignore_permissions=True)


class TestDeleteSalesWebhooks(FrappeTestCase):
	def test_deletes_every_sales_webhook(self):
		names = [make_webhook(path).name for path in delete_sales_webhooks.SALES_PATHS]
		sales_permission = make_webhook("/api/v1/user-permission-webhooks/", "sales", "User Permission")

		delete_sales_webhooks.execute()

		for name in [*names, sales_permission.name]:
			self.assertFalse(frappe.db.exists("Webhook", name), name)

	def test_keeps_hrm_and_unrelated_webhooks(self):
		hrm_permission = make_webhook("/api/v1/user-permission-webhooks/", "hr", "User Permission")
		employee = make_webhook("/api/v1/employee-webhook/", "hr", "Employee")
		other = make_webhook("/api/v1/something-else/")

		delete_sales_webhooks.execute()

		for webhook in (hrm_permission, employee, other):
			self.assertTrue(frappe.db.exists("Webhook", webhook.name), webhook.request_url)
