# mfr_serial_map/overrides/serial_no_search.py
#
# Registered as standard_queries["Serial No"] in hooks.py.
#
# Replaces the default Link-field autocomplete for every Serial No Link field
# across the entire application (forms, filters, reports).
#
# Search matches on:
#   • name          — internal serial (primary key)
#   • item_code     — standard field, always searched
#   • custom_mfr_ser — manufacturer serial
#
# The three-column result (name, item_code, custom_mfr_ser) means the
# manufacturer serial appears as a description hint in the dropdown, making it
# easy for operators to confirm they selected the right unit.

import json

import frappe


def serial_no_query(
	doctype,
	txt,
	searchfield,
	start,
	page_length,
	filters,
	as_dict=False,
	reference_doctype=None,
	ignore_user_permissions=False,
	link_fieldname=None,
):
	sn = frappe.qb.DocType("Serial No")
	txt_like = f"%{txt}%"

	query = (
		frappe.qb.from_(sn)
		.select(sn.name, sn.item_code, sn.custom_mfr_ser)
		.where(
			(sn.name.like(txt_like))
			| (sn.item_code.like(txt_like))
			| (sn.custom_mfr_ser.like(txt_like))
		)
		.limit(page_length)
		.offset(start)
	)

	# Apply caller-supplied filters (e.g. item_code injected by a set_query call)
	if filters:
		if isinstance(filters, str):
			filters = json.loads(filters)
		if isinstance(filters, dict):
			for key, val in filters.items():
				field = getattr(sn, key, None)
				if field is not None:
					query = query.where(field == val)

	return query.run()
