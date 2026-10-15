# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""Disable the webhooks that pushed HRM changes to this site's Arc-One API.

Step one of two, and the reversible one: Arc-One now reads the six HRM DocTypes
from the change feed, and this stops the webhooks writing the same rows a second
time. The documents are kept, so `hrm_webhooks.enable` puts them back.

They are deleted weeks later by `delete_hrm_webhooks`, which is added to
patches.txt once this one has been in place long enough to be sure nothing was
missed. Only webhooks calling this site's Arc-One API are touched; see
arc_one_bridge/utils/hrm_webhooks.py.
"""

from arc_one_bridge.utils import hrm_webhooks


def execute():
	hrm_webhooks.disable()
