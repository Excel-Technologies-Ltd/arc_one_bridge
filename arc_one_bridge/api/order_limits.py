# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""Customer limits lowered by an Arc-One order's approval.

Arc-One works out a customer's brand, other-brands and remaining-balance limits
from its own copy of the Customer. Writing the result back from that copy lost
updates - two approvals for one customer both started from the same copy and the
second overwrote the first - so Arc-One sends the amounts and ERPNext does the
subtraction, on the current row, under a lock.
"""

import json

import frappe

from arc_one_bridge.arc_one_bridge.doctype.arc_one_order_limit.arc_one_order_limit import (
	apply_order_limits as _apply_order_limits,
)


@frappe.whitelist(methods=["POST"])
def apply_order_limits(
	order: str,
	customer: str,
	total: float = 0,
	brand_amounts: dict | str | None = None,
	other_brands_amount: float = 0,
) -> dict:
	"""Lower `customer`'s limits by approved order `order`, once.

	`brand_amounts` maps brand to the order's amount for that brand. Safe to call
	again for the same order: the second call changes nothing and says so.
	"""
	# Changes a Customer, so it takes the caller's own right to change one rather
	# than the read-only sync role.
	frappe.has_permission("Customer", "write", customer, throw=True)

	if not order or not customer:
		frappe.throw(frappe._("An order number and a customer are required"))

	if isinstance(brand_amounts, str):
		brand_amounts = json.loads(brand_amounts or "{}")

	return _apply_order_limits(order, customer, total, brand_amounts or {}, other_brands_amount)
