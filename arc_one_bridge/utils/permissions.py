# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""Shared authorisation helpers for the bridge's whitelisted endpoints."""

import frappe

# The role Arc-One's API user should hold: read access to the feed and to the
# tracked DocTypes, nothing else. System Manager is still accepted so existing
# admin-key deployments keep working while they move to a dedicated user.
SYNC_ROLE = "Arc One Sync"
ADMIN_ROLE = "System Manager"


def has_sync_role(user: str | None = None) -> bool:
	roles = frappe.get_roles(user or frappe.session.user)
	return SYNC_ROLE in roles or ADMIN_ROLE in roles


def require_sync_role() -> None:
	"""Guard every bridge endpoint.

	Kept in one place so a new endpoint cannot accidentally ship without a check,
	and so the required role can be changed once rather than per method.
	"""
	if not has_sync_role():
		frappe.throw(
			frappe._("You are not authorised to access the Arc One sync feed"),
			frappe.PermissionError,
		)
