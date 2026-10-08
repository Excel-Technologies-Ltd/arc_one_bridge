# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""Feed ERPNext's daily Overdue marking into the Arc-One change log.

`erpnext.controllers.accounts_controller.update_invoice_status` sets invoices to
Overdue with one raw UPDATE: no `doc_events` fire and `modified` does not move, so
neither the change feed nor Arc-One's `modified` sweep can see it. This task runs
once after each run of that job and records the invoices it may have changed.

An invoice turns Overdue once any payment term - not only the final due date - is
past due, so both the invoice's due date and its Payment Schedule dates are
considered. Looking back a week instead of one day covers a run of this task that
was missed or overlapped the ERPNext job; re-recording an invoice only makes
Arc-One read it again.
"""

import frappe
from frappe.utils import add_days, getdate

from arc_one_bridge.arc_one_bridge.doctype.arc_one_change_log.arc_one_change_log import (
	ArcOneChangeLog,
)
from arc_one_bridge.arc_one_bridge.doctype.arc_one_sync_settings.arc_one_sync_settings import (
	is_tracked,
)

INVOICE_DOCTYPE = "Sales Invoice"
OVERDUE_JOB = "erpnext.controllers.accounts_controller.update_invoice_status"
LOOKBACK_DAYS = 7
# Which run of the ERPNext job was last followed up. Losing it (a cache flush) only
# repeats one follow-up.
LAST_FOLLOWED_KEY = "arc_one_bridge:overdue_followed_run"


def record_overdue_invoices() -> None:
	"""Hourly: record recently overdue invoices once per run of the ERPNext job."""
	if not is_tracked(INVOICE_DOCTYPE):
		return

	last_run = _last_completed_run()
	if not last_run or frappe.cache().get_value(LAST_FOLLOWED_KEY) == str(last_run):
		return

	for name in recently_overdue_invoices():
		ArcOneChangeLog.record(INVOICE_DOCTYPE, name, "update")
	frappe.db.commit()

	frappe.cache().set_value(LAST_FOLLOWED_KEY, str(last_run))


def _last_completed_run():
	"""When the ERPNext job last finished.

	With logging on, `last_execution` is stamped when a run starts, so a follow-up
	taken mid-run would mark it handled before its updates exist; the run's log
	turns Complete only at the end. Without logging, `last_execution` is stamped
	again on completion.
	"""
	job = frappe.db.get_value(
		"Scheduled Job Type",
		{"method": OVERDUE_JOB},
		["name", "create_log", "last_execution"],
		as_dict=True,
	)
	if not job:
		return None
	if not job.create_log:
		return job.last_execution
	return frappe.db.get_value(
		"Scheduled Job Log",
		{"scheduled_job_type": job.name, "status": "Complete"},
		"modified",
		order_by="modified desc",
	)


def recently_overdue_invoices(lookback_days: int = LOOKBACK_DAYS) -> list[str]:
	"""Overdue invoices with a due date or payment term that fell due in the window."""
	today = getdate()
	since = add_days(today, -lookback_days)

	invoice = frappe.qb.DocType(INVOICE_DOCTYPE)
	schedule = frappe.qb.DocType("Payment Schedule")
	overdue = (invoice.docstatus == 1) & invoice.status.like("Overdue%")

	by_due_date = (
		frappe.qb.from_(invoice)
		.select(invoice.name)
		.where(overdue & (invoice.due_date >= since) & (invoice.due_date < today))
	)
	by_payment_term = (
		frappe.qb.from_(invoice)
		.join(schedule)
		.on((schedule.parent == invoice.name) & (schedule.parenttype == INVOICE_DOCTYPE))
		.select(invoice.name)
		.distinct()
		.where(overdue & (schedule.due_date >= since) & (schedule.due_date < today))
	)

	names = {row[0] for row in by_due_date.run()} | {row[0] for row in by_payment_term.run()}
	return sorted(names)
