# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""Shared authorisation helpers for the bridge's whitelisted endpoints."""

import frappe

SYNC_ROLE = "System Manager"


def require_sync_role() -> None:
	"""Guard every bridge endpoint.

	Kept in one place so a new endpoint cannot accidentally ship without a check,
	and so the required role can be changed once rather than per method.
	"""
	if SYNC_ROLE not in frappe.get_roles(frappe.session.user):
		frappe.throw(
			frappe._("You are not authorised to access the Arc One sync feed"),
			frappe.PermissionError,
		)
