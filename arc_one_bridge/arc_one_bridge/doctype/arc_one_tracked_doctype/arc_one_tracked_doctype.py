# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ArcOneTrackedDocType(Document):
	"""One replicated DocType.

	A Link to DocType rather than free text on purpose: a typo in a plain-text list
	would silently stop replicating a document type, which is exactly the class of
	invisible failure this design exists to remove.
	"""

	pass
