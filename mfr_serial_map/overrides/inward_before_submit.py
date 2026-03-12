# mfr_serial_map/overrides/inward_before_submit.py
#
# Hooks into Serial and Batch Bundle.before_submit.
#
# WHY this event, not Purchase Invoice.before_submit:
#   For amended PIs (and in general for ERPNext v16), the SABB is created
#   during Purchase Invoice.on_submit, AFTER our before_submit hook would run.
#   By the time SABB.before_submit fires (during PI.on_submit), the bundle
#   entries hold the scanned OEM serials -- and no SLEs have been written yet.
#
# The hook modifies doc.entries in-place (used by ERPNext to write SLEs) and
# also updates the DB rows via _patch_entry(), so both the in-flight
# transaction and any future lookup see the internal serial names.

import frappe
from frappe.model.naming import make_autoname
from frappe.model.rename_doc import rename_doc

INWARD_VOUCHERS = {"Purchase Receipt", "Purchase Invoice", "Stock Entry"}


@frappe.whitelist()
def get_effective_series(item_code):
	"""Return a description of the series used for internal serial generation."""
	series = frappe.get_cached_value("Item", item_code, "serial_no_series")
	if series:
		return series
	rules = frappe.get_all(
		"Document Naming Rule",
		filters={"document_type": "Serial No", "disabled": 0},
		fields=["prefix"],
		order_by="priority desc",
		limit=1,
	)
	if rules:
		return rules[0].prefix or "(Document Naming Rule)"
	return None


def _get_next_internal_serial(item_code):
	"""
	Determine the next internal serial name using, in order:
	  1. Item.serial_no_series  (explicit per-item series)
	  2. Document Naming Rule for Serial No  (global rule, e.g. CA-.YY..MM..DD.-.####)
	Raises a descriptive error if neither is configured.
	"""
	series = frappe.get_cached_value("Item", item_code, "serial_no_series")
	if not series:
		rules = frappe.get_all(
			"Document Naming Rule",
			filters={"document_type": "Serial No", "disabled": 0},
			fields=["prefix"],
			order_by="priority desc",
			limit=1,
		)
		if rules:
			series = rules[0].prefix

	if not series:
		frappe.throw(
			f"Item {frappe.bold(item_code)} has <b>Generate Internal Serial No</b> enabled "
			f"but no series is defined. Set <b>Serial Number Series</b> on the item, or "
			f"create a <b>Document Naming Rule</b> for Serial No in Setup."
		)

	name = make_autoname(series, "Serial No")
	# Guard against collisions (same logic as get_new_serial_number)
	if frappe.db.exists("Serial No", name):
		return _get_next_internal_serial(item_code)
	return name


def remap_serials_sabb(doc, method):
	"""
	Serial and Batch Bundle -- before_submit.

	Fires during the parent voucher's on_submit, after bundle entries are
	populated but before Stock Ledger Entries are written.

	Renames every OEM-named Serial No in the bundle to an internal serial,
	stores the OEM name in custom_mfr_ser, and patches doc.entries in-place
	so the upstream SLE writer sees the internal names.
	"""
	if doc.type_of_transaction != "Inward":
		return
	if doc.voucher_type not in INWARD_VOUCHERS:
		return
	if not frappe.get_cached_value("Item", doc.item_code, "custom_generate_internal_serial"):
		return

	for entry in doc.entries:
		mfr_serial = entry.serial_no
		if not mfr_serial:
			continue

		# Idempotency: already remapped in a previous attempt on this bundle.
		already = frappe.db.get_value(
			"Serial No",
			{"custom_mfr_ser": mfr_serial, "item_code": doc.item_code},
			"name",
		)
		if already:
			_patch_entry(entry, already)
			continue

		# Uniqueness guard for concurrent submissions.
		conflict = frappe.db.get_value(
			"Serial No",
			{"custom_mfr_ser": mfr_serial, "item_code": doc.item_code},
			"name",
		)
		if conflict:
			frappe.throw(
				f"MFR Serial <b>{mfr_serial}</b> already exists for item "
				f"<b>{doc.item_code}</b> as internal serial <b>{conflict}</b>. "
				f"Each manufacturer serial must be unique per item."
			)

		internal_serial = _get_next_internal_serial(doc.item_code)

		if frappe.db.exists("Serial No", mfr_serial):
			# Standard path: rename the OEM-named stub to the internal name.
			rename_doc(
				"Serial No",
				mfr_serial,
				internal_serial,
				ignore_permissions=True,
				rebuild_search=False,
			)
		else:
			# Fallback: serial was never pre-created (amended PI, bulk import, etc.)
			sn = frappe.new_doc("Serial No")
			sn.serial_no = internal_serial
			sn.item_code = doc.item_code
			sn.flags.ignore_permissions = True
			sn.insert(ignore_permissions=True)

		# Store OEM serial on the renamed/created record.
		frappe.db.set_value("Serial No", internal_serial, "custom_mfr_ser", mfr_serial)

		# Keep the full-text global search index in sync.
		frappe.db.sql(
			"""UPDATE `__global_search`
			   SET content = %s
			   WHERE doctype = 'Serial No' AND name = %s""",
			(f"{internal_serial} {mfr_serial} {doc.item_code}", internal_serial),
		)

		_patch_entry(entry, internal_serial)


def _patch_entry(entry, internal_serial):
	"""
	Update the Serial and Batch Entry row both in-memory and in the DB.

	In-memory change: ERPNext reads doc.entries when writing SLEs, so this
	ensures the SLE is written with the internal serial name.

	DB change: persists the rename for future lookups and the bundle view.
	"""
	entry.serial_no = internal_serial
	if entry.name:
		frappe.db.set_value(
			"Serial and Batch Entry",
			entry.name,
			"serial_no",
			internal_serial,
			update_modified=False,
		)


# -- Legacy voucher-level handlers (now no-ops) --------------------------------
# SABB.before_submit handles all cases uniformly. These stubs prevent errors
# if they are still referenced in hooks.py during any transition period.

def remap_serials(doc, method):
	"""Purchase Receipt -- handled via SABB.before_submit."""
	pass


def remap_serials_pi(doc, method):
	"""Purchase Invoice -- handled via SABB.before_submit."""
	pass


def remap_serials_se(doc, method):
	"""Stock Entry -- handled via SABB.before_submit."""
	pass
