# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

import frappe

from arc_one_bridge.utils.permissions import SYNC_ROLE


def after_install():
	ensure_sync_access()


def after_migrate():
	ensure_sync_access()


def ensure_sync_access() -> None:
	"""Create the sync role and give it read access to every tracked DocType.

	Arc-One fetches current state through /api/resource, so the sync user needs
	read permission on each replicated DocType - and only that.
	"""
	ensure_sync_role()

	try:
		settings = frappe.get_single("Arc One Sync Settings")
	except Exception:
		return

	for row in settings.tracked_doctypes or []:
		if row.enabled:
			grant_read(row.document_type)


def ensure_sync_role() -> None:
	if frappe.db.exists("Role", SYNC_ROLE):
		return
	frappe.get_doc(
		{
			"doctype": "Role",
			"role_name": SYNC_ROLE,
			"desk_access": 1,
			"description": "Read-only API access for Arc-One replication.",
		}
	).insert(ignore_permissions=True)


def grant_read(doctype: str) -> None:
	"""Add a read rule for the sync role, leaving any existing rule untouched.

	Only permlevel 0: fields on a higher permlevel are not returned to the sync
	user and so cannot be replicated without a further, deliberate grant.
	"""
	if not frappe.db.exists("DocType", doctype):
		return
	if frappe.db.exists(
		"Custom DocPerm", {"parent": doctype, "role": SYNC_ROLE, "permlevel": 0, "if_owner": 0}
	):
		return

	from frappe.permissions import add_permission

	add_permission(doctype, SYNC_ROLE, 0)
