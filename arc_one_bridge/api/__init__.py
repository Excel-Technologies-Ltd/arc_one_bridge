# Copyright (c) 2026, Excel Technologies Limited and contributors
# For license information, please see license.txt

"""Whitelisted endpoints Arc-One calls.

Split by concern rather than gathered into one module:

* `change_feed`    - the cursor-based feed and its head position
* `reconciliation` - cheap drift detection against a replica

Every endpoint guards with `utils.permissions.require_sync_role`.
"""
