# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

import frappe

from arc_one_bridge.utils.permissions import SYNC_ROLE


IOU_KEY_FIELD = {
	"fieldname": "arc_one_key",
	"label": "Arc-One Key",
	"fieldtype": "Data",
	"read_only": 1,
	"search_index": 1,
	"no_copy": 1,
	"print_hide": 1,
	"description": "Set by Arc-One for offline approvals. Used to avoid applying a change twice.",
}


def after_install():
	ensure_sync_access()
	ensure_iou_key_fields()


def after_migrate():
	ensure_sync_access()
	ensure_iou_key_fields()


def ensure_iou_key_fields() -> None:
	"""Add the Arc-One key to the IoU DocTypes, so Arc-One can tell whether a change already reached ERPNext.

	Idempotent: an existing field is updated in place, not duplicated.
	"""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(
		{
			"Employee Advance": [IOU_KEY_FIELD],
			"IoU Project": [IOU_KEY_FIELD],
		},
		ignore_validate=True,
	)


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
