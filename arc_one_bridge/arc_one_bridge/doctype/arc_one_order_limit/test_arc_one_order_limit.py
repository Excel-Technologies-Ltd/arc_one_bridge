# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from arc_one_bridge.arc_one_bridge.doctype.arc_one_order_limit.arc_one_order_limit import (
	ORDER_LIMIT_DOCTYPE,
	apply_order_limits,
)

CUSTOMER = "_Test Arc One Limits Customer"
BRAND_A = "_Test Arc One Brand A"
BRAND_B = "_Test Arc One Brand B"


class TestArcOneOrderLimit(FrappeTestCase):
	def setUp(self):
		for brand in (BRAND_A, BRAND_B):
			if not frappe.db.exists("Brand", brand):
				frappe.get_doc({"doctype": "Brand", "brand": brand}).insert(ignore_permissions=True)

		frappe.db.delete(ORDER_LIMIT_DOCTYPE, {"customer": CUSTOMER})
		if frappe.db.exists("Customer", CUSTOMER):
			frappe.delete_doc("Customer", CUSTOMER, force=True)

		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": CUSTOMER,
				"name": CUSTOMER,
				"custom_other_brands_limit": 500,
				"excel_remaining_balance": 1000,
				"custom_brand_wise_allocations": [
					{"brand": BRAND_A, "limit": 300},
					{"brand": BRAND_B, "limit": 100},
				],
			}
		).insert(ignore_permissions=True, ignore_mandatory=True, set_name=CUSTOMER)

	def tearDown(self):
		frappe.db.rollback()

	def _customer(self):
		doc = frappe.get_doc("Customer", CUSTOMER)
		brands = {row.brand: row.limit for row in doc.custom_brand_wise_allocations}
		return brands, doc.custom_other_brands_limit, doc.excel_remaining_balance

	def test_lowers_each_limit_by_the_order(self):
		result = apply_order_limits("ASO-T-1", CUSTOMER, 250, {BRAND_A: 120}, 80)

		self.assertTrue(result["applied"])
		self.assertEqual(self._customer(), ({BRAND_A: 180, BRAND_B: 100}, 420, 750))

		log = frappe.get_doc(ORDER_LIMIT_DOCTYPE, "ASO-T-1")
		self.assertEqual(log.customer, CUSTOMER)
		self.assertEqual(json.loads(log.changes)["excel_remaining_balance"], {"before": 1000, "after": 750})

	def test_applying_the_same_order_again_changes_nothing(self):
		apply_order_limits("ASO-T-1", CUSTOMER, 250, {BRAND_A: 120}, 80)
		again = apply_order_limits("ASO-T-1", CUSTOMER, 250, {BRAND_A: 120}, 80)

		self.assertFalse(again["applied"])
		self.assertEqual(self._customer(), ({BRAND_A: 180, BRAND_B: 100}, 420, 750))

	def test_two_orders_for_one_customer_both_count(self):
		apply_order_limits("ASO-T-1", CUSTOMER, 100, {BRAND_A: 100}, 0)
		apply_order_limits("ASO-T-2", CUSTOMER, 50, {BRAND_A: 50}, 0)

		self.assertEqual(self._customer(), ({BRAND_A: 150, BRAND_B: 100}, 500, 850))

	def test_never_below_zero_and_unallocated_brands_ignored(self):
		apply_order_limits("ASO-T-1", CUSTOMER, 5000, {BRAND_B: 999, "Not Allocated": 10}, 900)

		self.assertEqual(self._customer(), ({BRAND_A: 300, BRAND_B: 0}, 0, 0))
