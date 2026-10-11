# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""Delete the webhooks that pushed Sales changes to Arc-One.

Arc-One now reads every Sales DocType from the change feed, and the endpoints these
webhooks called no longer exist; left in place they only fill the Webhook Request
Log with failures. HRM's webhooks are kept, including its User Permission ones,
which call the same endpoint as the Sales ones but are marked `x-module: hr`.
"""

import frappe

SALES_PATHS = (
	"/api/v1/brands-webhook/",
	"/api/v1/customer-webhook/",
	"/api/v1/item-webhook/",
	"/api/v1/item-stock-webhook/",
	"/api/v1/sales-person-webhooks/",
	"/api/v1/territory-webhook/",
	"/api/v1/warehouse-webhook/",
	"/api/v1/sales-invoice-webhook/",
	"/api/v1/item-price-webhook/",
	"/api/v1/item-group-webhooks/",
	"/api/v1/zones-webhook/",
)
USER_PERMISSION_PATH = "/api/v1/user-permission-webhooks/"


def execute():
	for name in sales_webhooks():
		frappe.delete_doc("Webhook", name, ignore_permissions=True)


def sales_webhooks() -> list[str]:
	hrm = set(hrm_webhooks())
	return [
		webhook.name
		for webhook in frappe.get_all("Webhook", fields=["name", "request_url"])
		if any(path in (webhook.request_url or "") for path in SALES_PATHS)
		or (USER_PERMISSION_PATH in (webhook.request_url or "") and webhook.name not in hrm)
	]


def hrm_webhooks() -> list[str]:
	header = frappe.qb.DocType("Webhook Header")
	return (
		frappe.qb.from_(header)
		.select(header.parent)
		.where(header.parenttype == "Webhook")
		.where(header.key == "x-module")
		.where(header.value == "hr")
		.run(pluck=True)
	)
