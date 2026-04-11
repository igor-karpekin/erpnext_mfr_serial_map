# mfr_serial_map/overrides/serial_batch.py
#
# Overrides two whitelisted APIs via override_whitelisted_methods:
#
#  1. is_serial_batch_no_exists  — called per scan in the SABB dialog scan field.
#  2. create_serial_nos          — called when the user enters serials manually
#                                  (textarea / serial-range / CSV upload) and
#                                  clicks "Add Serial Nos".
#
# Both entry points use the same strategy for opted-in items:
#
#   - Create the Serial No stub immediately with the correct internal name via
#     raw SQL INSERT (no Frappe document layer, no hooks, no toast).
#   - Store the scanned / typed OEM value in custom_mfr_ser.
#   - Leave the bundle entry's serial_no as the OEM value (the JS controls
#     that field); SABB.before_submit patches the entry to the internal serial.
#
# Cases (Inward):
#   a) Brand-new OEM serial → _create_serial_stub (internal name, mfr_ser stored).
#   b) OEM serial already mapped from a prior receipt → no new stub needed.
#
# Cases (Outward — e.g. manufacturing consumption):
#   c) OEM barcode scanned → find internal serial via custom_mfr_ser → skip throw.
#      add_serial_batch_ledgers translates OEM → internal before saving.
#   d) OEM barcode not found in mapping → fall through to _original (raises error).
#
# Cases (non-opted-in item, batch, etc.):
#   e) → fall through to _original.

import frappe
from frappe.utils import parse_json
from erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle import (
	add_serial_batch_ledgers as _original_add_serial_batch_ledgers,
	create_serial_nos as _original_create_serial_nos,
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
def add_serial_batch_ledgers(entries, child_row, doc, warehouse, do_not_save=False):
	"""
	Translate OEM serial values in entries to internal serial names before the
	SABB is saved.  This is necessary because:
	  - The browser always stores the raw scanned / typed OEM value in the entry.
	  - SABB.serial_no is a Link field; Frappe validates it on save.
	  - Our scan/manual hooks created the stub with the internal name, so the
	    OEM value would fail link validation without this translation.
	"""
	if isinstance(child_row, str):
		child_row_dict = frappe._dict(parse_json(child_row))
	else:
		child_row_dict = frappe._dict(child_row)

	item_code = child_row_dict.get("item_code")

	if item_code and frappe.get_cached_value("Item", item_code, "custom_generate_internal_serial"):
		if isinstance(entries, str):
			entries_list = parse_json(entries)
		else:
			entries_list = list(entries)

		translated = []
		for row in entries_list:
			row = dict(frappe._dict(row))
			oem = row.get("serial_no")
			if oem:
				existing_item = frappe.db.get_value("Serial No", oem, "item_code")
				# Translate if serial doesn't exist at all, OR exists but for a
				# different item (cross-item OEM barcode reuse, e.g. TWR chassis
				# serial reused as identifier for finished DSK good).
				if existing_item != item_code:
					internal = frappe.db.get_value(
						"Serial No",
						{"custom_mfr_ser": oem, "item_code": item_code},
						"name",
					)
					if internal:
						row["serial_no"] = internal
			translated.append(row)
		entries = translated

	return _original_add_serial_batch_ledgers(entries, child_row, doc, warehouse, do_not_save=do_not_save)


@frappe.whitelist()
def create_serial_nos(item_code, serial_nos):
	"""
	Called when the user enters serials manually (textarea, range, or CSV).

	For opted-in items: create Serial No stubs with internal names via
	_create_serial_stub instead of letting ERPNext's make_serial_nos create
	them with OEM names.

	The returned list still uses the OEM serial as the 'serial_no' key so the
	dialog entries table (and ultimately the SABB) store the OEM value.
	SABB.before_submit then patches the entries to the internal serial.
	"""
	if not frappe.get_cached_value("Item", item_code, "custom_generate_internal_serial"):
		return _original_create_serial_nos(item_code, serial_nos)

	if isinstance(serial_nos, str):
		oem_serials = [s.strip() for s in serial_nos.splitlines() if s.strip()]
	else:
		oem_serials = [s.strip() for s in serial_nos if s.strip()]

	entries = []
	for oem_serial in oem_serials:
		# Skip if already mapped (re-receipt of a known OEM serial)
		already = frappe.db.get_value("Serial No", {"custom_mfr_ser": oem_serial}, "name")
		if not already and not frappe.db.exists("Serial No", oem_serial):
			_create_serial_stub(oem_serial, item_code)
		entries.append({"serial_no": oem_serial, "qty": 1})

	return entries


@frappe.whitelist()
def is_serial_batch_no_exists(item_code, type_of_transaction, serial_no=None, batch_no=None):
	if serial_no and frappe.get_cached_value("Item", item_code, "custom_generate_internal_serial"):
		existing_item = frappe.db.get_value("Serial No", serial_no, "item_code")
		# serial_exists is True only if it exists AND belongs to the same item.
		serial_exists = existing_item == item_code

		if not serial_exists:
			# Either doesn't exist at all, or exists but for a different item (cross-item
			# OEM barcode reuse, e.g. same chassis serial used for both TWR component and
			# DSK finished good). Treat as OEM barcode for the current item.
			already_mapped = frappe.db.get_value(
				"Serial No", {"custom_mfr_ser": serial_no, "item_code": item_code}, "name"
			)

			if type_of_transaction == "Inward":
				if not already_mapped:
					# Brand-new OEM serial on receipt — create stub with internal name.
					_create_serial_stub(serial_no, item_code)
				# Stub created or already mapped — skip _original entirely.
				return

			if type_of_transaction == "Outward":
				if already_mapped:
					# Known OEM barcode scanned for consumption (e.g. manufacturing).
					# add_serial_batch_ledgers will translate OEM → internal before saving.
					return
				# No mapping found — fall through to original to throw the proper error.

	return _original(item_code, type_of_transaction, serial_no=serial_no, batch_no=batch_no)
