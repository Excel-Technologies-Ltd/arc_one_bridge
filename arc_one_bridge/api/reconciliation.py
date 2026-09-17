# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""Drift detection against an Arc-One replica.

The change feed only observes writes that pass through the ORM. `frappe.db.set_value`,
raw SQL and direct database edits fire no `doc_events`, so the feed alone is never
proof that two systems agree. Comparing these figures against the replica catches
the common case for the cost of one aggregate query per DocType.
"""

import frappe
from frappe.query_builder.functions import Count, Max

from arc_one_bridge.utils.permissions import require_sync_role


@frappe.whitelist()
def reconcile(doctype: str) -> dict:
	"""Row count and newest `modified` for one DocType."""
	require_sync_role()

	if not frappe.db.exists("DocType", doctype):
		frappe.throw(frappe._("Unknown DocType: {0}").format(doctype))

	# Query builder rather than an interpolated table name: `doctype` arrives from
	# the caller, and frappe.qb quotes the identifier for us.
	table = frappe.qb.DocType(doctype)
	result = (
		frappe.qb.from_(table).select(
			Count("*").as_("count"), Max(table.modified).as_("max_modified")
		)
	).run(as_dict=True)[0]

	return {
		"doctype": doctype,
		"count": result.get("count") or 0,
		"max_modified": result.get("max_modified"),
	}
