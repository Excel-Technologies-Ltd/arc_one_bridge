# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document
from frappe.utils import flt

ORDER_LIMIT_DOCTYPE = "Arc One Order Limit"


class ArcOneOrderLimit(Document):
	"""Record that an approved Arc-One order lowered its customer's limits.

	Named by the order number, so the record is the idempotency key: applying an
	order a second time - a retry after a timeout, two Arc-One instances at once -
	finds it and changes nothing.
	"""


def apply_order_limits(
	order: str, customer: str, total: float, brand_amounts: dict, other_brands_amount: float
) -> dict:
	"""Lower `customer`'s limits by an approved order, at most once per order.

	Lowers each allocated brand's limit by that brand's amount in the order, the
	other-brands limit by the rest, and the remaining balance by the order total,
	none below zero - the rules Arc-One applied when it wrote these fields itself.

	The Customer row is locked before anything is read, so two orders for one
	customer are applied one after the other, each from the other's result,
	instead of both from the same starting values with the second overwriting the
	first. The order is checked against the log only once the lock is held.

	Returns `{"applied": True, "changes": ...}`, or `{"applied": False}` when the
	order had already been applied.
	"""
	doc = frappe.get_doc("Customer", customer, for_update=True)

	if frappe.db.exists(ORDER_LIMIT_DOCTYPE, order):
		return {"applied": False}

	changes = {}

	for row in doc.get("custom_brand_wise_allocations") or []:
		amount = flt(brand_amounts.get(row.brand))
		if amount:
			changes[f"brand:{row.brand}"] = _lower(row, "limit", amount)

	if flt(other_brands_amount):
		changes["custom_other_brands_limit"] = _lower(doc, "custom_other_brands_limit", other_brands_amount)

	if flt(total):
		changes["excel_remaining_balance"] = _lower(doc, "excel_remaining_balance", total)

	# Only limits change here: a customer missing an unrelated mandatory field (older
	# records predate some) must not have its limits left unlowered because of it.
	doc.flags.ignore_mandatory = True
	doc.save()

	frappe.get_doc(
		{
			"doctype": ORDER_LIMIT_DOCTYPE,
			"order": order,
			"customer": customer,
			"total": flt(total),
			"other_brands_amount": flt(other_brands_amount),
			"brand_amounts": json.dumps(brand_amounts),
			"changes": json.dumps(changes),
		}
	).insert(ignore_permissions=True)

	return {"applied": True, "changes": changes}


def _lower(doc, fieldname: str, amount: float) -> dict:
	"""Lower `doc.fieldname` by `amount`, not below zero; returns before and after."""
	before = flt(doc.get(fieldname))
	after = max(before - flt(amount), 0)
	doc.set(fieldname, after)
	return {"before": before, "after": after}
