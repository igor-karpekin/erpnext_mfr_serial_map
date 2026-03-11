# mfr_serial_map/overrides/serial_no_validate.py
#
# Fires on every Serial No before_save.
# Guards the uniqueness of custom_mfr_ser within a single item_code.
# The DB-level unique index (added by the install patch) is the hard stop;
# this check provides the human-readable error message first.

import frappe


def validate_mfr_ser_unique(doc, method):
	if not doc.custom_mfr_ser:
		return

	conflict = frappe.db.get_value(
		"Serial No",
		{
			"custom_mfr_ser": doc.custom_mfr_ser,
			"item_code": doc.item_code,
			"name": ("!=", doc.name),
		},
		"name",
	)
	if conflict:
		frappe.throw(
			f"MFR Serial <b>{doc.custom_mfr_ser}</b> is already assigned "
			f"to internal serial <b>{conflict}</b> for item <b>{doc.item_code}</b>. "
			f"Manufacturer serials must be unique per item."
		)
