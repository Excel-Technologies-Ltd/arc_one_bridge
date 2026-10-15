# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""Delete the HRM webhooks that `disable_hrm_webhooks` turned off.

Step two of two, and the one that cannot be undone from here: recreating these
webhooks means reverting the Arc-One commit that removed `hrm-webhook-data.ts`
and calling `/api/v1/hrm/webhook/create-all`.

It deletes only webhooks that are already disabled, and only once
`disable_hrm_webhooks` has been in place for MIN_DAYS_DISABLED. A site that
migrates both patches in one run therefore disables them now and deletes them on
a later migrate, which is the point of the wait.
"""

from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from arc_one_bridge.utils import hrm_webhooks

DISABLE_PATCH = "arc_one_bridge.patches.disable_hrm_webhooks"
MIN_DAYS_DISABLED = 14


def execute():
	disabled_at = frappe.db.get_value("Patch Log", {"patch": DISABLE_PATCH}, "creation")
	if not disabled_at:
		print(f"delete_hrm_webhooks skipped: {DISABLE_PATCH} has not run on this site")
		return

	due = disabled_at + timedelta(days=MIN_DAYS_DISABLED)
	if now_datetime() < due:
		print(f"delete_hrm_webhooks skipped: the webhooks were disabled on {disabled_at:%Y-%m-%d}, deleting from {due:%Y-%m-%d}")
		return

	hrm_webhooks.delete()
