# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""Retire the webhooks that pushed HRM changes to this site's Arc-One API.

Arc-One reads Attendance, Employee Checkin, Holiday List, Shift Type, Attendance
Request and Leave Application from the change feed, so these webhooks only fill
the Webhook Request Log with failures once the receivers are gone.

Retirement is two steps, weeks apart, and both run by `bench migrate` as patches,
the same way the Sales webhooks were retired (`patches/delete_sales_webhooks.py`):

	arc_one_bridge.patches.disable_hrm_webhooks   reversible, run first
	arc_one_bridge.patches.delete_hrm_webhooks    added to patches.txt later

The functions here hold the behaviour so the patches stay thin and so `enable`
is available by hand for a rollback:

	bench --site <site> execute arc_one_bridge.utils.hrm_webhooks.enable

Webhooks are matched by the host they call as well as the path, as in
delete_sales_webhooks: only those calling this site's Arc-One API
(`arc_one_api_base_url` in site_config.json) are touched. The User, User
Permission and Employee webhooks are not part of this and are kept. Without the
setting nothing is touched, and the caller is told why.
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
	return _set_enabled(0, "disable", dry_run)


def enable(dry_run=False):
	return _set_enabled(1, "enable", dry_run)


def delete(dry_run=False):
	host = api_host()
	if not host:
		return _skipped("delete")

	webhooks = [webhook for webhook in hrm_webhooks(host) if not webhook.enabled]
	if not _is_dry(dry_run):
		for webhook in webhooks:
			frappe.delete_doc("Webhook", webhook.name, ignore_permissions=True)
	return _report("delete", webhooks, dry_run)


def _set_enabled(value, action, dry_run):
	host = api_host()
	if not host:
		return _skipped(action)

	webhooks = [webhook for webhook in hrm_webhooks(host) if webhook.enabled != value]
	if not _is_dry(dry_run):
		for webhook in webhooks:
			frappe.db.set_value("Webhook", webhook.name, "enabled", value)
		frappe.cache().delete_value("webhooks")
	return _report(action, webhooks, dry_run)


def hrm_webhooks(host: str):
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


def _skipped(action):
	"""Nothing to match against. Said, not raised: a patch must not stop a migrate."""
	print(f"hrm_webhooks.{action} skipped: set {API_BASE_URL_KEY} in site_config.json")
	return {"action": action, "skipped": f"{API_BASE_URL_KEY} is not set", "webhooks": []}


def _report(action, webhooks, dry_run):
	report = {
		"action": action,
		"dry_run": _is_dry(dry_run),
		"webhooks": [[w.name, w.webhook_doctype, w.request_url] for w in webhooks],
	}
	print(f"hrm_webhooks.{action}: {len(webhooks)} webhook(s){' (dry run)' if report['dry_run'] else ''}")
	for name, doctype, url in report["webhooks"]:
		print(f"  {name}  {doctype}  {url}")
	return report
