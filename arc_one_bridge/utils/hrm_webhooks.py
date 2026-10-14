# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""Retire the webhooks that pushed HRM changes to this site's Arc-One API.

Arc-One reads Attendance, Employee Checkin, Holiday List, Shift Type, Attendance
Request and Leave Application from the change feed. Retirement is two steps, run
by hand on the HRM site, weeks apart:

	bench --site <site> execute arc_one_bridge.utils.hrm_webhooks.disable
	bench --site <site> execute arc_one_bridge.utils.hrm_webhooks.delete

`disable` is reversed by `enable`. `delete` removes only webhooks already
disabled, so it cannot run before the first step. Every function takes
`dry_run=True` to list what it would touch.

Webhooks are matched by the host they call as well as the path, as in
delete_sales_webhooks: only those calling this site's Arc-One API
(`arc_one_api_base_url` in site_config.json) are touched. The User, User
Permission and Employee webhooks are not part of this and are kept.
"""

from urllib.parse import urlparse

import frappe

HRM_PATHS = (
	"/api/v1/hrm/attendance/",
	"/api/v1/hrm/employee-checkin/",
	"/api/v1/hrm/holiday-list/",
	"/api/v1/hrm/leave-application/",
	"/api/v1/shifts-webhook/",
	"/api/v1/attendance-request-webhook/",
	"/api/v1/leave-application/",
)
API_BASE_URL_KEY = "arc_one_api_base_url"


def disable(dry_run=False):
	return _set_enabled(0, dry_run)


def enable(dry_run=False):
	return _set_enabled(1, dry_run)


def delete(dry_run=False):
	webhooks = [webhook for webhook in hrm_webhooks() if not webhook.enabled]
	if not _is_dry(dry_run):
		for webhook in webhooks:
			frappe.delete_doc("Webhook", webhook.name, ignore_permissions=True)
	return _report("deleted", webhooks, dry_run)


def _set_enabled(value, dry_run):
	webhooks = [webhook for webhook in hrm_webhooks() if webhook.enabled != value]
	if not _is_dry(dry_run):
		for webhook in webhooks:
			frappe.db.set_value("Webhook", webhook.name, "enabled", value)
		frappe.cache().delete_value("webhooks")
	return _report("enabled" if value else "disabled", webhooks, dry_run)


def hrm_webhooks():
	host = api_host()
	if not host:
		frappe.throw(f"Set {API_BASE_URL_KEY} in site_config.json to the Arc-One API this site calls")
	return [
		webhook
		for webhook in frappe.get_all("Webhook", fields=["name", "enabled", "webhook_doctype", "request_url"])
		if is_hrm_webhook(webhook.request_url, host)
	]


def api_host() -> str:
	return urlparse(frappe.conf.get(API_BASE_URL_KEY) or "").netloc


def is_hrm_webhook(request_url, host: str) -> bool:
	url = urlparse(request_url or "")
	return url.netloc == host and url.path.startswith(HRM_PATHS)


def _is_dry(dry_run) -> bool:
	return dry_run not in (False, 0, "0", "false", "False", None, "")


def _report(action, webhooks, dry_run):
	return {
		"action": action,
		"dry_run": _is_dry(dry_run),
		"webhooks": [[w.name, w.webhook_doctype, w.request_url] for w in webhooks],
	}
