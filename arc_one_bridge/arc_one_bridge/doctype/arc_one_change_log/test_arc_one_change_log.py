# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.rename_doc import rename_doc
from frappe.tests.utils import FrappeTestCase

from frappe.utils import add_days, cint, nowdate

from arc_one_bridge.api.change_feed import acknowledge, changes, cursor_head
from arc_one_bridge.arc_one_bridge.doctype.arc_one_change_log.arc_one_change_log import (
	ArcOneChangeLog,
	_insert_rows,
)
from arc_one_bridge.events.change_recorder import _derived_targets
from arc_one_bridge.install import ensure_sync_access
from arc_one_bridge.utils.permissions import SYNC_ROLE

TRACKED = "Brand"
PREFIX = "_Test Arc One Brand"

# Rows are only written when a transaction commits, so these tests commit for real
# and clean up after themselves.


def _log_rows(after: int) -> list:
	return frappe.get_all(
		"Arc One Change Log",
		filters={"name": (">", after), "ref_doctype": TRACKED},
		fields=["name", "ref_name", "event"],
		order_by="name asc",
	)


def _head() -> int:
	return frappe.db.sql("select ifnull(max(name), 0) from `tabArc One Change Log`")[0][0]


class TestArcOneChangeLog(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Arc One Sync Settings")
		cls.original = {
			"enabled": settings.enabled,
			"settle_seconds": settings.settle_seconds,
			"tracked": [(r.document_type, r.enabled) for r in settings.tracked_doctypes],
		}
		settings.enabled = 1
		settings.settle_seconds = 0
		if not any(r.document_type == TRACKED for r in settings.tracked_doctypes):
			settings.append("tracked_doctypes", {"document_type": TRACKED, "enabled": 1})
		settings.save()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		for name in frappe.get_all(TRACKED, filters={"name": ("like", f"{PREFIX}%")}, pluck="name"):
			frappe.delete_doc(TRACKED, name, force=True)
		settings = frappe.get_single("Arc One Sync Settings")
		settings.enabled = cls.original["enabled"]
		settings.settle_seconds = cls.original["settle_seconds"]
		settings.tracked_doctypes = []
		for doctype, enabled in cls.original["tracked"]:
			settings.append("tracked_doctypes", {"document_type": doctype, "enabled": enabled})
		settings.save()
		frappe.db.commit()
		super().tearDownClass()

	def _brand(self, suffix: str):
		return frappe.get_doc({"doctype": TRACKED, "brand": f"{PREFIX} {suffix}"})

	def test_one_row_per_document_per_commit(self):
		head = _head()
		doc = self._brand("collapse").insert()
		doc.description = "first"
		doc.save()
		doc.description = "second"
		doc.save()
		self.assertEqual(_log_rows(head), [], "rows must wait for the commit")

		frappe.db.commit()

		rows = _log_rows(head)
		self.assertEqual([(r.ref_name, r.event) for r in rows], [(doc.name, "update")])

	def test_rollback_records_nothing(self):
		head = _head()
		self._brand("rolled back").insert()
		frappe.db.rollback()
		frappe.db.commit()

		self.assertEqual(_log_rows(head), [])

	def test_cursor_follows_commit_order(self):
		head = _head()
		first = self._brand("order a").insert()
		frappe.db.commit()
		second = self._brand("order b").insert()
		frappe.db.commit()

		rows = _log_rows(head)
		self.assertEqual([r.ref_name for r in rows], [first.name, second.name])
		self.assertLess(rows[0].name, rows[1].name)

	def test_rename_records_old_and_new(self):
		doc = self._brand("rename old").insert()
		frappe.db.commit()
		head = _head()

		new_name = f"{PREFIX} rename new"
		rename_doc(TRACKED, doc.name, new_name, force=True)
		frappe.db.commit()

		rows = _log_rows(head)
		events = {(r.ref_name, r.event) for r in rows}
		self.assertIn((doc.name, "trash"), events)
		self.assertIn((new_name, "update"), events)

	def test_delete_records_trash(self):
		doc = self._brand("delete").insert()
		frappe.db.commit()
		head = _head()

		frappe.delete_doc(TRACKED, doc.name)
		frappe.db.commit()

		self.assertEqual([(r.ref_name, r.event) for r in _log_rows(head)], [(doc.name, "trash")])

	def test_settle_window_withholds_young_rows(self):
		head = _head()
		self._brand("settle").insert()
		frappe.db.commit()

		frappe.db.set_single_value("Arc One Sync Settings", "settle_seconds", 3600)
		frappe.db.commit()
		try:
			withheld = changes(after=head, doctypes=[TRACKED])
			self.assertEqual(withheld["changes"], [])
			self.assertEqual(withheld["cursor"], head)
		finally:
			frappe.db.set_single_value("Arc One Sync Settings", "settle_seconds", 0)
			frappe.db.commit()

		released = changes(after=head, doctypes=[TRACKED])
		self.assertEqual(len(released["changes"]), 1)

	def _set_bin_tracked(self, enabled: int):
		settings = frappe.get_single("Arc One Sync Settings")
		row = next((r for r in settings.tracked_doctypes if r.document_type == "Bin"), None)
		if row:
			row.enabled = enabled
		else:
			settings.append("tracked_doctypes", {"document_type": "Bin", "enabled": enabled})
		settings.save()
		frappe.db.commit()

	def test_stock_ledger_entry_records_its_bin(self):
		bin_row = frappe.db.get_value("Bin", {}, ["name", "item_code", "warehouse"], as_dict=True)
		if not bin_row:
			self.skipTest("no Bin on this site")
		entry = frappe._dict(
			doctype="Stock Ledger Entry", item_code=bin_row.item_code, warehouse=bin_row.warehouse
		)

		self._set_bin_tracked(1)
		self.assertEqual(_derived_targets(entry), [("Bin", bin_row.name)])

		self._set_bin_tracked(0)
		self.assertEqual(_derived_targets(entry), [], "an untracked Bin is not recorded")

	def test_sync_role_gets_read_on_tracked_doctypes(self):
		ensure_sync_access()

		self.assertTrue(frappe.db.exists("Role", SYNC_ROLE))
		perm = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": TRACKED, "role": SYNC_ROLE, "permlevel": 0},
			["read", "write", "create", "delete"],
			as_dict=True,
		)
		self.assertEqual((perm.read, perm.write, perm.create, perm.delete), (1, 0, 0, 0))

	def test_idle_cursor_advances_to_head(self):
		self._brand("idle").insert()
		frappe.db.commit()

		# Nothing for this DocType, yet the cursor moves past the Brand row: a quiet
		# DocType must not sit on an old cursor that pruning later reads as a gap.
		page = changes(after=0, doctypes=["DocType Nobody Tracks"])
		self.assertEqual(page["changes"], [])
		self.assertEqual(page["cursor"], _head())

	def test_cursor_stops_at_the_page_when_more_is_waiting(self):
		head = _head()
		for i in range(3):
			self._brand(f"page {i}").insert()
			frappe.db.commit()

		page = changes(after=head, limit=2, doctypes=[TRACKED])
		self.assertTrue(page["has_more"])
		self.assertEqual(page["cursor"], page["changes"][-1]["name"])


class TestChangeLogRetention(FrappeTestCase):
	"""Pruning against Arc-One's acknowledged cursor.

	Every test back-dates only its own rows - hundreds of days - and prunes with
	windows just short of that, so no real change log row on the site qualifies.
	"""

	SETTINGS = "Arc One Sync Settings"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.original = {
			field: frappe.db.get_single_value(cls.SETTINGS, field)
			for field in ("acknowledged_cursor", "acknowledged_at", "pruned_through")
		}

	@classmethod
	def tearDownClass(cls):
		frappe.db.set_single_value(cls.SETTINGS, cls.original)
		frappe.db.commit()
		super().tearDownClass()

	def _old_rows(self, count: int, days: int) -> list:
		"""Write `count` log rows back-dated `days` days; returns their cursors."""
		start = _head()
		_insert_rows([((TRACKED, f"{PREFIX} retention {i}"), "update") for i in range(count)])
		frappe.db.sql(
			"update `tabArc One Change Log` set creation = %s where name > %s",
			(add_days(nowdate(), -days), start),
		)
		frappe.db.commit()
		return [
			row[0]
			for row in frappe.db.sql("select name from `tabArc One Change Log` where name > %s order by name", start)
		]

	def _exists(self, names: list) -> list:
		return [bool(frappe.db.exists("Arc One Change Log", name)) for name in names]

	def _prune(self):
		ArcOneChangeLog.prune(retention_days=399, max_retention_days=500)

	def test_keeps_old_rows_arc_one_has_not_acknowledged(self):
		rows = self._old_rows(3, days=400)
		frappe.db.set_single_value(self.SETTINGS, "acknowledged_cursor", rows[0])

		self._prune()
		self.assertEqual(self._exists(rows), [False, True, True])

	def test_drops_unacknowledged_rows_past_the_hard_limit_and_records_it(self):
		rows = self._old_rows(2, days=600)
		frappe.db.set_single_value(self.SETTINGS, "acknowledged_cursor", 0)

		self._prune()
		self.assertEqual(self._exists(rows), [False, False])
		self.assertGreaterEqual(cint(frappe.db.get_single_value(self.SETTINGS, "pruned_through")), rows[-1])

	def test_pruned_through_never_moves_back(self):
		frappe.db.set_single_value(self.SETTINGS, "pruned_through", 10**12)
		rows = self._old_rows(1, days=600)

		self._prune()
		self.assertEqual(self._exists(rows), [False])
		self.assertEqual(cint(frappe.db.get_single_value(self.SETTINGS, "pruned_through")), 10**12)

	def test_acknowledge_records_and_refuses_a_cursor_beyond_the_head(self):
		head = _head()
		self.assertEqual(acknowledge(head)["acknowledged_cursor"], head)
		self.assertEqual(cint(frappe.db.get_single_value(self.SETTINGS, "acknowledged_cursor")), head)

		with self.assertRaises(frappe.ValidationError):
			acknowledge(head + 1)

	def test_cursor_head_reports_pruned_through(self):
		frappe.db.set_single_value(self.SETTINGS, "pruned_through", 42)
		self.assertEqual(cursor_head()["pruned_through"], 42)
