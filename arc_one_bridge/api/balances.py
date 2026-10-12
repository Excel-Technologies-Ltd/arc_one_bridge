# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""Customer outstanding balances, many at a time.

Arc-One's customer lists show each customer's balance. Asking
`erpnext.accounts.utils.get_balance_on` once per customer made a page of fifty
customers fifty requests; this answers the page in one query, with the same rule.
"""

import json

import frappe
from erpnext.accounts.utils import FiscalYearError, get_fiscal_year
from frappe.query_builder.functions import Sum
from frappe.utils import cstr, flt, getdate, nowdate

MAX_CUSTOMERS = 500


@frappe.whitelist()
def customer_balances(customers: list | str, date: str | None = None) -> dict:
	"""Each customer's balance on `date`, as `get_balance_on(date, "Customer", customer)` gives it.

	That is: debits less credits in account currency over the customer's GL entries
	up to `date` that are not cancelled - 0 for a customer with none - and 0 for all
	when `date` is older than any fiscal year.
	"""
	frappe.has_permission("GL Entry", "read", throw=True)

	if isinstance(customers, str):
		customers = json.loads(customers or "[]")
	customers = [cstr(customer) for customer in customers or [] if customer]
	if len(customers) > MAX_CUSTOMERS:
		frappe.throw(frappe._("At most {0} customers at a time").format(MAX_CUSTOMERS))
	if not customers:
		return {}

	date = cstr(date) if date else nowdate()
	balances = {customer: 0.0 for customer in customers}

	# get_balance_on's rule: a date older than any fiscal year has no balance at all
	try:
		get_fiscal_year(date, verbose=0)
	except FiscalYearError:
		if getdate(date) <= getdate(nowdate()):
			return balances

	gle = frappe.qb.DocType("GL Entry")
	rows = (
		frappe.qb.from_(gle)
		.select(
			gle.party,
			(Sum(gle.debit_in_account_currency) - Sum(gle.credit_in_account_currency)).as_("balance"),
		)
		.where(gle.is_cancelled == 0)
		.where(gle.posting_date <= date)
		.where(gle.party_type == "Customer")
		.where(gle.party.isin(customers))
		.groupby(gle.party)
	).run(as_dict=True)

	for row in rows:
		balances[row.party] = flt(row.balance)
	return balances
