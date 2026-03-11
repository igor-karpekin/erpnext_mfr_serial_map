# mfr_serial_map/overrides/serial_batch.py
#
# Overrides is_serial_batch_no_exists via override_whitelisted_methods.
#
# This function is called by the Serial & Batch Bundle dialog's scan field
# (serial_no_batch_selector.js) on every barcode scan *before* the bundle
# entry is saved.  The standard implementation creates a new Serial No doc
# if the scanned value does not exist — using the scanned value verbatim as
# the document name.
#
# For opted-in items the scanned value is the manufacturer serial.  Two
# cases are handled:
#
#   a) The manufacturer serial was already received and remapped in a prior
#      transaction → a Serial No with custom_mfr_ser = <scanned> exists.
#      We substitute the internal name so the bundle entry records the
#      correct (internal) serial from the start.
#
#   b) Brand-new manufacturer serial → pass through unchanged.  The standard
#      implementation creates the Serial No with name = <mfr_serial>, and
#      before_submit will rename it to the internal serial when the voucher
#      is submitted.

import frappe
from erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle import (
	is_serial_batch_no_exists as _original,
)


@frappe.whitelist()
def is_serial_batch_no_exists(item_code, type_of_transaction, serial_no=None, batch_no=None):
	if (
		serial_no
		and frappe.get_cached_value("Item", item_code, "custom_generate_internal_serial")
		and not frappe.db.exists("Serial No", serial_no)
	):
		# Check whether this is a manufacturer serial that maps to an existing
		# internal serial (re-receipt scenario or lookup after first mapping).
		internal = frappe.db.get_value(
			"Serial No", {"custom_mfr_ser": serial_no}, "name"
		)
		if internal:
			serial_no = internal

	return _original(item_code, type_of_transaction, serial_no=serial_no, batch_no=batch_no)
