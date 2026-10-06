# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

TRACKED_CACHE_KEY = "arc_one_bridge:tracked_doctypes"


class ArcOneSyncSettings(Document):
	def on_update(self):
		# The change hooks consult this on every write in the site, so it is cached.
		# Without this the cache would go stale until the next restart and an admin's
		# edit would appear to do nothing.
		clear_tracked_cache()

		from arc_one_bridge.install import ensure_sync_access

		ensure_sync_access()


def get_tracked_doctypes() -> frozenset:
	"""DocTypes currently being recorded.

	Cached, because this is consulted by a hook that fires on every document write
	in the site and so must never reach the database on the hot path.
	"""
	cached = frappe.cache().get_value(TRACKED_CACHE_KEY)
	if cached is not None:
		return frozenset(cached)

	try:
		settings = frappe.get_cached_doc("Arc One Sync Settings")
	except Exception:
		# Before the first `bench migrate` the Single does not exist yet. Record
		# nothing rather than break every save on the site.
		return frozenset()

	tracked = (
		frozenset(row.document_type for row in (settings.tracked_doctypes or []) if row.enabled)
		if settings.enabled
		else frozenset()
	)

	frappe.cache().set_value(TRACKED_CACHE_KEY, list(tracked))
	return tracked


def is_tracked(doctype: str) -> bool:
	"""Whether changes to `doctype` should be recorded."""
	return doctype in get_tracked_doctypes()


def clear_tracked_cache() -> None:
	frappe.cache().delete_value(TRACKED_CACHE_KEY)
