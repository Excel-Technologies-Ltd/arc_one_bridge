# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""Drift detection against an Arc-One replica.

The change feed only observes writes that pass through the ORM. `frappe.db.set_value`,
raw SQL and direct database edits fire no `doc_events`, so the feed alone is never
proof that two systems agree. Comparing these figures against the replica catches
the common case for the cost of one aggregate query per DocType.
"""

import frappe
from frappe.query_builder import CustomFunction
from frappe.query_builder.functions import Count, Max, Min, Sum

from arc_one_bridge.arc_one_bridge.doctype.arc_one_sync_settings.arc_one_sync_settings import (
	is_tracked,
)
from arc_one_bridge.utils.permissions import ADMIN_ROLE, require_sync_role


@frappe.whitelist()
def reconcile(doctype: str) -> dict:
	"""Row count and newest `modified` for one DocType."""
	require_sync_role()

	if not frappe.db.exists("DocType", doctype):
		frappe.throw(frappe._("Unknown DocType: {0}").format(doctype))

	# The sync role reads replicated DocTypes only; counting arbitrary tables is
	# left to administrators.
	if not is_tracked(doctype) and ADMIN_ROLE not in frappe.get_roles():
		frappe.throw(
			frappe._("{0} is not replicated to Arc-One").format(doctype), frappe.PermissionError
		)

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


INVOICE_DOCTYPE = "Sales Invoice"
DateFormat = CustomFunction("DATE_FORMAT", ["date", "format"])


@frappe.whitelist()
def invoice_summary(from_date: str, to_date: str) -> dict:
	"""Sales Invoice count and total per posting month and status, between two dates inclusive.

	Lets the replica be compared month by month, so a difference points at the
	month to re-read instead of all of the table. Bounded by date because a whole
	table of millions in one grouped query outlasts the caller's timeout; the
	oldest posting date says how far back the caller has to go.
	"""
	require_sync_role()
	if not is_tracked(INVOICE_DOCTYPE):
		frappe.throw(
			frappe._("{0} is not replicated to Arc-One").format(INVOICE_DOCTYPE), frappe.PermissionError
		)

	invoice = frappe.qb.DocType(INVOICE_DOCTYPE)
	month = DateFormat(invoice.posting_date, "%Y-%m")
	rows = (
		frappe.qb.from_(invoice)
		.select(
			month.as_("month"),
			invoice.status,
			Count("*").as_("count"),
			Sum(invoice.total).as_("total"),
		)
		.where(invoice.posting_date.between(from_date, to_date))
		.groupby(month, invoice.status)
	).run(as_dict=True)

	first_date = frappe.qb.from_(invoice).select(Min(invoice.posting_date)).run()[0][0]

	return {
		"first_date": str(first_date) if first_date else None,
		"months": [
			{
				"month": row.month,
				"status": row.status,
				"count": row["count"],
				"total": float(row.total or 0),
			}
			for row in rows
		],
	}
