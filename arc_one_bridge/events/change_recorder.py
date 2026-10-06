# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""`doc_events` handlers that feed the Arc-One change log.

A wildcard hook fires these on every document write in the site, so they stay
deliberately thin: resolve the document to a (DocType, name) pair, check it is
tracked, and hand off to `ArcOneChangeLog.record`. The record-keeping itself
belongs to that DocType's controller, not here.

They never raise. Refusing a user's save because a replication row could not be
written would be the worse outcome; the gap is caught by the `modified` watermark
sweep and the nightly checksums on the Arc-One side, which exist because
`doc_events` cannot observe every write (see INT-15 in the Arc-One audit).
"""

import frappe

from arc_one_bridge.arc_one_bridge.doctype.arc_one_change_log.arc_one_change_log import (
	ArcOneChangeLog,
)
from arc_one_bridge.arc_one_bridge.doctype.arc_one_sync_settings.arc_one_sync_settings import (
	is_tracked,
)

# The bridge's own bookkeeping is never recorded: writing a change log row would
# otherwise record a change log row.
OWN_DOCTYPES = frozenset(
	{
		"Arc One Change Log",
		"Arc One Sync Settings",
		"Arc One Tracked DocType",
	}
)


def _resolve_target(doc) -> tuple:
	"""Map a written document to the document Arc-One should re-fetch.

	Child rows change as part of their parent, so the parent is recorded instead -
	a consumer fetching one coherent document rather than an orphaned row.
	"""
	doctype = getattr(doc, "doctype", None)
	if not doctype or doctype in OWN_DOCTYPES:
		return None, None

	if getattr(doc, "parenttype", None):
		return doc.parenttype, getattr(doc, "parent", None)

	return doctype, getattr(doc, "name", None)


def _record(doc, event: str) -> None:
	try:
		doctype, name = _resolve_target(doc)
		if not doctype or not name or not is_tracked(doctype):
			return

		ArcOneChangeLog.record(doctype, str(name), event)

	except Exception:
		# Swallowed deliberately - see the module docstring.
		frappe.log_error(
			title="Arc One Bridge: failed to record change",
			message=frappe.get_traceback(),
		)


def on_insert(doc, method=None):
	_record(doc, "insert")


def on_update(doc, method=None):
	_record(doc, "update")


def on_submit(doc, method=None):
	_record(doc, "submit")


def on_cancel(doc, method=None):
	_record(doc, "cancel")


def on_trash(doc, method=None):
	# The one event a consumer cannot reconstruct by fetching current state: once
	# the document is gone there is nothing left to read. This is the main reason a
	# plain /api/resource poll cannot replace this feed.
	_record(doc, "trash")


def on_rename(doc, method=None, old=None, new=None, merge=False):
	# A rename rewrites `name` with SQL and fires no on_update, so without this the
	# replica keeps the old name forever. Recorded as the old name going away and
	# the new one appearing; with `merge` the old document is gone the same way.
	try:
		doctype = getattr(doc, "doctype", None)
		if not doctype or doctype in OWN_DOCTYPES or not is_tracked(doctype):
			return

		if old:
			ArcOneChangeLog.record(doctype, str(old), "trash")
		ArcOneChangeLog.record(doctype, str(new or doc.name), "update")

	except Exception:
		frappe.log_error(
			title="Arc One Bridge: failed to record rename",
			message=frappe.get_traceback(),
		)
