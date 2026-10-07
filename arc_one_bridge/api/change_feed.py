# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""The cursor-based change feed.

Pull-based on purpose. A push design (Frappe Webhooks) cannot survive the
*receiver* being down: anything dispatched while Arc-One is restarting or
deploying is lost for good. A cursor the consumer owns makes recovery the normal
path rather than a special case - if Arc-One was offline for an hour, its next
poll simply catches up, and the same holds if this site was the one offline.
"""

import frappe
from frappe.query_builder.functions import Count, Max
from frappe.utils import add_to_date, cint, now_datetime

from arc_one_bridge.utils.permissions import require_sync_role

CHANGE_LOG = "Arc One Change Log"
DEFAULT_LIMIT = 500
MAX_LIMIT = 2000


def _settle_seconds() -> int:
	return max(cint(frappe.db.get_single_value("Arc One Sync Settings", "settle_seconds")), 0)


def _parse_doctypes(doctypes) -> list:
	"""Accept a JSON list, a comma-separated string, or a real list."""
	if not doctypes:
		return []
	if isinstance(doctypes, str):
		stripped = doctypes.strip()
		if stripped.startswith("["):
			return frappe.parse_json(stripped) or []
		return [part.strip() for part in stripped.split(",") if part.strip()]
	return list(doctypes)


@frappe.whitelist()
def changes(after=0, limit=DEFAULT_LIMIT, doctypes=None) -> dict:
	"""Return change rows after a cursor.

	Args:
	    after: the last cursor the consumer applied; 0 starts from the beginning.
	    limit: page size, capped at MAX_LIMIT.
	    doctypes: optional subset, so independent consumers can own different
	        DocTypes without reading each other's traffic.

	Returns:
	    cursor:   highest name in this page - pass as `after` next time. Unchanged
	              from the request when there is nothing new. Rows younger than
	              the settle window are withheld until a later call.
	    has_more: whether a further page is immediately available.
	    changes:  [{name, ref_doctype, ref_name, event, creation}] ascending.

	The consumer should collapse the page to distinct (ref_doctype, ref_name) and
	fetch current state, rather than treating rows as deltas. That is what makes
	re-reading a page after a crash harmless.
	"""
	require_sync_role()

	after = frappe.utils.cint(after)
	limit = max(1, min(frappe.utils.cint(limit) or DEFAULT_LIMIT, MAX_LIMIT))

	filters = {"name": (">", after)}
	selected = _parse_doctypes(doctypes)
	if selected:
		filters["ref_doctype"] = ("in", selected)

	settle = _settle_seconds()
	if settle:
		filters["creation"] = ("<", add_to_date(now_datetime(), seconds=-settle))

	rows = frappe.get_all(
		CHANGE_LOG,
		filters=filters,
		fields=["name", "ref_doctype", "ref_name", "event", "creation"],
		order_by="name asc",
		limit=limit,
	)
	has_more = len(rows) == limit

	cursor = rows[-1]["name"] if rows else after
	if not has_more:
		# Nothing more for these DocTypes up to the settled head, so the cursor can
		# move to it. Otherwise a DocType that rarely changes keeps its cursor on its
		# last change for months: it reads as far behind, and once that row is pruned
		# it would look like it missed rows - every quiet DocType forced into a
		# needless full re-sync.
		log = frappe.qb.DocType(CHANGE_LOG)
		head = frappe.qb.from_(log).select(Max(log.name))
		if settle:
			head = head.where(log.creation < filters["creation"][1])
		cursor = max(cint(cursor), cint(head.run()[0][0]))

	return {
		"cursor": cursor,
		"has_more": has_more,
		"changes": rows,
	}


@frappe.whitelist(methods=["POST"])
def acknowledge(cursor) -> dict:
	"""Record the lowest cursor the consumer still needs; rows at or below it may be pruned.

	Arc-One sends the minimum over all of its DocType cursors for this site. A
	cursor beyond the head is refused: accepting it would let pruning delete rows
	nobody has read.
	"""
	require_sync_role()

	cursor = cint(cursor)
	log = frappe.qb.DocType(CHANGE_LOG)
	head = cint(frappe.qb.from_(log).select(Max(log.name)).run()[0][0])
	if cursor < 0 or cursor > head:
		frappe.throw(frappe._("Cursor {0} is outside the change log (head {1})").format(cursor, head))

	# Written directly: saving the Single would run its on_update, which re-applies
	# sync permissions - work an acknowledgement every minute must not trigger.
	frappe.db.set_single_value(
		"Arc One Sync Settings", {"acknowledged_cursor": cursor, "acknowledged_at": now_datetime()}
	)
	return {"acknowledged_cursor": cursor}


@frappe.whitelist()
def cursor_head() -> dict:
	"""Newest cursor, how many rows are retained, and how far pruning has reached.

	Lets a consumer report its own lag without walking the feed. `pruned_through`
	is what reveals when retention has passed a stalled consumer by: a cursor below
	it missed rows, and needs a full re-sync rather than an incremental catch-up.
	"""
	require_sync_role()

	log = frappe.qb.DocType(CHANGE_LOG)
	result = (
		frappe.qb.from_(log).select(Max(log.name).as_("head"), Count("*").as_("rows_kept"))
	).run(as_dict=True)[0]

	return {
		"head": result.get("head") or 0,
		"rows_kept": result.get("rows_kept") or 0,
		"pruned_through": cint(frappe.db.get_single_value("Arc One Sync Settings", "pruned_through")),
	}
