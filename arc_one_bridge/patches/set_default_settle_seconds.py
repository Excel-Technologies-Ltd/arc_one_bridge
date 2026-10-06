import frappe

SETTINGS = "Arc One Sync Settings"


def execute():
	# A field added to an existing Single gets no row in tabSingles, and reads back
	# as 0 - which would silently disable the settle window on every upgraded site.
	if frappe.db.exists("Singles", {"doctype": SETTINGS, "field": "settle_seconds"}):
		return
	frappe.db.set_single_value(SETTINGS, "settle_seconds", 5)
