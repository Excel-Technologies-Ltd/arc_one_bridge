# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder.functions import Max
from frappe.utils import add_days, cint, now, nowdate

DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_RETENTION_DAYS = 90

CHANGE_LOG_TABLE = "tabArc One Change Log"
CHANGE_LOG_SEQUENCE = "arc_one_change_log_id_seq"
INSERT_CHUNK = 500


class ArcOneChangeLog(Document):
	"""An append-only record that a tracked document changed.

	Deliberately stores no payload. Arc-One reads a batch of these rows, collapses
	them to distinct (ref_doctype, ref_name) and fetches the CURRENT state of each
	document. Applying current state is idempotent, so replaying any range of the
	log converges on the same result, and a document edited fifty times collapses
	into a single fetch.

	`name` comes from a sequence and is the cursor. A sequence value is taken when
	a row is inserted, not when its transaction commits, so a row inserted early in
	a long transaction would become visible *after* higher cursors and a consumer
	that had already moved past it would never see it. Rows are therefore staged in
	memory and inserted in `before_commit`, milliseconds before COMMIT: cursor order
	then follows commit order, the rows commit atomically with the business data,
	and a rolled-back transaction leaves nothing behind. `changes()` additionally
	withholds rows younger than the settle window to cover the remaining race.
	"""

	@classmethod
	def record(cls, ref_doctype: str, ref_name: str, event: str) -> None:
		"""Stage one change for the open transaction.

		The single place a log row is created, so callers - today the `doc_events`
		handlers, tomorrow anything else - cannot diverge on how rows are shaped.
		"""
		_pending_changes().add(ref_doctype, ref_name, event)

	@staticmethod
	def prune(retention_days: int | None = None, max_retention_days: int | None = None) -> None:
		"""Remove rows Arc-One no longer needs.

		A row goes once it is older than `retention_days` AND at or below the cursor
		Arc-One acknowledged. Deleting by age alone dropped rows a stalled consumer
		had not read yet - it could never get them back, and could not tell.

		Past `max_retention_days` a row goes regardless, so a consumer that is gone
		for good cannot grow the log forever. `pruned_through` records the highest
		row ever deleted: a consumer whose cursor is below it knows rows were lost
		before it read them and re-syncs instead of carrying on with a silent gap.
		"""
		settings = "Arc One Sync Settings"
		if retention_days is None:
			retention_days = frappe.db.get_single_value(settings, "retention_days") or DEFAULT_RETENTION_DAYS
		if max_retention_days is None:
			max_retention_days = (
				frappe.db.get_single_value(settings, "max_retention_days") or DEFAULT_MAX_RETENTION_DAYS
			)
		acknowledged = cint(frappe.db.get_single_value(settings, "acknowledged_cursor"))

		log = frappe.qb.DocType("Arc One Change Log")
		cutoff = add_days(nowdate(), -int(retention_days))
		hard_cutoff = add_days(nowdate(), -max(int(max_retention_days), int(retention_days)))
		prunable = ((log.creation < cutoff) & (log.name <= acknowledged)) | (log.creation < hard_cutoff)

		highest = frappe.qb.from_(log).select(Max(log.name)).where(prunable).run()[0][0]
		if not highest:
			return

		frappe.qb.from_(log).delete().where(prunable).run()
		if cint(highest) > cint(frappe.db.get_single_value(settings, "pruned_through")):
			frappe.db.set_single_value(settings, "pruned_through", cint(highest))
		frappe.db.commit()


class PendingChanges:
	"""Changes recorded in the open transaction, waiting for its commit.

	Keyed by (doctype, name) and kept in order of each document's latest change:
	the consumer only acts on the last event per document, so repeated saves in one
	transaction collapse to one row.
	"""

	def __init__(self):
		self.rows: dict[tuple[str, str], str] = {}

	def add(self, ref_doctype: str, ref_name: str, event: str) -> None:
		if not self.rows:
			# Rollback observers are reset by every commit and rollback, so register
			# again for each transaction that records something.
			frappe.local.rollback_observers.append(self)

		key = (ref_doctype, ref_name)
		self.rows.pop(key, None)
		self.rows[key] = event

	def on_rollback(self) -> None:
		self.rows.clear()


def _pending_changes() -> PendingChanges:
	pending = getattr(frappe.local, "arc_one_pending_changes", None)
	if pending is None:
		pending = PendingChanges()
		frappe.local.arc_one_pending_changes = pending
		# `before_commit` lives for the whole request or job and runs before every
		# COMMIT in it, so one registration covers each later transaction too.
		frappe.db.add_before_commit(flush_pending_changes)
	return pending


def flush_pending_changes() -> None:
	"""Insert the staged rows into the transaction that is about to commit."""
	pending = getattr(frappe.local, "arc_one_pending_changes", None)
	if not pending or not pending.rows:
		return

	rows = list(pending.rows.items())
	pending.rows.clear()

	try:
		_insert_rows(rows)
	except Exception as e:
		# A deadlock has already rolled back the business writes; swallowing it would
		# let the COMMIT that follows report success for a save that did not happen.
		if frappe.db.is_deadlocked(e):
			raise
		frappe.log_error(
			title="Arc One Bridge: failed to write change log",
			message=frappe.get_traceback(),
		)


def _insert_rows(rows: list) -> None:
	timestamp = now()
	user = getattr(frappe.session, "user", None) or "Administrator"

	for start in range(0, len(rows), INSERT_CHUNK):
		chunk = rows[start : start + INSERT_CHUNK]
		placeholders = ", ".join(
			f"(nextval(`{CHANGE_LOG_SEQUENCE}`), %s, %s, %s, %s, %s, %s, %s)" for _ in chunk
		)
		values = []
		for (ref_doctype, ref_name), event in chunk:
			values.extend((timestamp, timestamp, user, user, ref_doctype, ref_name, event))

		frappe.db.sql(
			f"""insert into `{CHANGE_LOG_TABLE}`
				(name, creation, modified, modified_by, owner, ref_doctype, ref_name, event)
			values {placeholders}""",
			values,
		)


def prune_change_log() -> None:
	"""Scheduler entry point - see `hooks.scheduler_events`."""
	ArcOneChangeLog.prune()
