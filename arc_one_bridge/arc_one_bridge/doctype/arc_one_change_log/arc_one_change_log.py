# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, nowdate

DEFAULT_RETENTION_DAYS = 30


class ArcOneChangeLog(Document):
	"""An append-only record that a tracked document changed.

	Deliberately stores no payload. Arc-One reads a batch of these rows, collapses
	them to distinct (ref_doctype, ref_name) and fetches the CURRENT state of each
	document. Applying current state is idempotent, so replaying any range of the
	log converges on the same result, and a document edited fifty times collapses
	into a single fetch.

	`name` is an autoincrementing integer, which is the cursor: monotonic, gap-free
	and self-ordering, so a consumer only has to remember the last value it applied.
	"""

	@classmethod
	def record(cls, ref_doctype: str, ref_name: str, event: str) -> None:
		"""Append one change.

		The single place a log row is created, so callers - today the `doc_events`
		handlers, tomorrow anything else - cannot diverge on how rows are shaped.
		"""
		frappe.get_doc(
			{
				"doctype": "Arc One Change Log",
				"ref_doctype": ref_doctype,
				"ref_name": ref_name,
				"event": event,
			}
		).insert(ignore_permissions=True)

	@staticmethod
	def prune(retention_days: int | None = None) -> None:
		"""Remove rows older than the retention window.

		Retention must comfortably exceed the longest expected consumer outage: a
		consumer whose cursor falls off the end of the log cannot catch up
		incrementally and has to be re-seeded with a full sync.
		"""
		if retention_days is None:
			retention_days = (
				frappe.db.get_single_value("Arc One Sync Settings", "retention_days")
				or DEFAULT_RETENTION_DAYS
			)

		cutoff = add_days(nowdate(), -int(retention_days))
		frappe.db.delete("Arc One Change Log", {"creation": ("<", cutoff)})
		frappe.db.commit()


def prune_change_log() -> None:
	"""Scheduler entry point - see `hooks.scheduler_events`."""
	ArcOneChangeLog.prune()
