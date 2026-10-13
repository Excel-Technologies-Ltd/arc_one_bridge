# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""Delete the webhooks that pushed Sales changes to this site's Arc-One API.

Arc-One now reads every Sales DocType from the change feed, and the endpoints these
webhooks called no longer exist; left in place they only fill the Webhook Request
Log with failures.

Webhooks are matched by the host they call as well as the path, because other
Arc-One deployments (and other applications) can register webhooks with the same
paths on the same ERPNext site. Only webhooks that call this site's Arc-One API are
deleted. HRM's webhooks (`x-module: hr`) are always kept, including their User
Permission ones, which use the same path as the Sales ones.

The Arc-One API host comes from `arc_one_api_base_url` in site_config.json. If it is
not set, nothing is deleted.
"""

from urllib.parse import urlparse

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
API_BASE_URL_KEY = "arc_one_api_base_url"


def execute():
	host = api_host()
	if not host:
		print(f"delete_sales_webhooks skipped: set {API_BASE_URL_KEY} in site_config.json")
		return

	for name in sales_webhooks(host):
		frappe.delete_doc("Webhook", name, ignore_permissions=True)


def api_host() -> str:
	base_url = frappe.conf.get(API_BASE_URL_KEY) or ""
	return urlparse(base_url).netloc


def sales_webhooks(host: str) -> list[str]:
	hrm = set(hrm_webhooks())
	return [
		webhook.name
		for webhook in frappe.get_all("Webhook", fields=["name", "request_url"])
		if webhook.name not in hrm and is_sales_webhook(webhook.request_url, host)
	]


def is_sales_webhook(request_url, host: str) -> bool:
	url = urlparse(request_url or "")
	if url.netloc != host:
		return False
	return url.path.startswith(SALES_PATHS) or url.path.startswith(USER_PERMISSION_PATH)


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
