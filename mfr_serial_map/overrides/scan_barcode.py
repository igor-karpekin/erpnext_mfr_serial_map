# mfr_serial_map/overrides/scan_barcode.py
#
# Overrides erpnext.stock.utils.scan_barcode via override_whitelisted_methods.
#
# Execution order:
#   1. Try the standard lookup (internal serial name, Item Barcode table,
#      Batch, Warehouse) by calling the original function directly.
#   2. If nothing is found, attempt a lookup by Serial No.custom_mfr_ser.
#
# Importing the original function from its module is safe: the override
# mechanism patches the whitelist registry entry point but does NOT replace
# the Python module attribute, so the import below always resolves to the
# upstream implementation.

import frappe
from erpnext.stock.utils import scan_barcode as _original_scan_barcode


@frappe.whitelist()
def scan_barcode(search_value: str, ctx=None) -> dict:
	# Standard lookup first
	result = _original_scan_barcode(search_value, ctx)
	if result:
		return result

	# Fallback: resolve by manufacturer serial stored in custom_mfr_ser
	sn = frappe.db.get_value(
		"Serial No",
		{"custom_mfr_ser": search_value},
		["name as serial_no", "item_code", "batch_no"],
		as_dict=True,
	)
	return sn or {}
