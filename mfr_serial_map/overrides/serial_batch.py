# mfr_serial_map/overrides/serial_batch.py
#
# Overrides is_serial_batch_no_exists via override_whitelisted_methods.
#
# Called by the Serial & Batch Bundle dialog scan field on every barcode scan
# BEFORE the bundle entry row is added.
#
# For opted-in items we create the Serial No stub here with the correct
# internal name (CA-YYMMDD-####) immediately, storing the scanned OEM value
# in custom_mfr_ser.  This means:
#
#   - No "document created" toast (we bypass frappe.new_doc().save()).
#   - No rename at submit time (stub already has the right name).
#   - SABB.before_submit only needs to patch the bundle entry from the scanned
#     OEM value to the internal serial (a cheap single-row UPDATE).
#
# Cases:
#   a) Brand-new OEM serial → create stub internally (internal name, mfr_ser stored).
#   b) OEM serial already mapped from a prior receipt → look up the existing
#      internal serial; no new stub needed.
#   c) Non-opted-in item, outward, batch, etc. → fall through to _original.

import frappe
from erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle import (
	is_serial_batch_no_exists as _original,
)
from mfr_serial_map.overrides.inward_before_submit import _get_series, _next_serial


def _create_serial_stub(oem_serial, item_code):
	"""
	Create a Serial No with the internal name directly via SQL.
	No document hooks fire, no toast is shown.
	"""
	series = _get_series(item_code)
	internal_serial = _next_serial(series)
	frappe.db.sql(
		"""INSERT INTO `tabSerial No`
		   (name, serial_no, item_code, custom_mfr_ser, docstatus,
		    creation, modified, owner, modified_by)
		   VALUES (%s, %s, %s, %s, 0, NOW(), NOW(), %s, %s)""",
		(internal_serial, internal_serial, item_code, oem_serial,
		 frappe.session.user, frappe.session.user),
	)


@frappe.whitelist()
def is_serial_batch_no_exists(item_code, type_of_transaction, serial_no=None, batch_no=None):
	if (
		serial_no
		and type_of_transaction == "Inward"
		and frappe.get_cached_value("Item", item_code, "custom_generate_internal_serial")
		and not frappe.db.exists("Serial No", serial_no)
	):
		# Check whether this OEM serial was already received and remapped.
		already_mapped = frappe.db.get_value(
			"Serial No", {"custom_mfr_ser": serial_no}, "name"
		)
		if not already_mapped:
			# Brand-new OEM serial — create the stub with the internal name now.
			_create_serial_stub(serial_no, item_code)
		# Either way, the Serial No is handled — skip _original entirely.
		return

	return _original(item_code, type_of_transaction, serial_no=serial_no, batch_no=batch_no)
