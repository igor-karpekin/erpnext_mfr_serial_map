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
# WHY we do NOT use rename_doc:
#   rename_doc scans all doctypes for Link fields pointing to Serial No and
#   issues UPDATE statements on each of them.  For a freshly-created stub
#   (no SLEs, no transfers, no other references) every one of those UPDATEs
#   is a no-op, but the metadata fetch alone costs ~2-3 s per serial.
#   For a 20-serial receipt that adds ~60 s to submission time.
#   Instead we do a single direct SQL UPDATE on tabSerial No and update the
#   one legitimate reference (tabSerial and Batch Entry) ourselves.

import frappe
from frappe.model.naming import make_autoname

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


def _get_series(item_code):
	"""Return the naming series string for this item (resolves once per bundle)."""
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
	return series


def _next_serial(series):
	"""Generate the next unique internal serial name from a series string."""
	name = make_autoname(series, "Serial No")
	if frappe.db.exists("Serial No", name):
		return _next_serial(series)
	return name


def _fast_rename_serial(mfr_serial, internal_serial, item_code):
	"""
	Rename a freshly-created Serial No stub without using rename_doc.

	At SABB.before_submit time the stub has no Stock Ledger Entries and no
	other document links -- rename_doc's cross-doctype link scan is therefore
	pure overhead (~2-3 s per serial).  A direct SQL UPDATE is safe here
	and reduces the cost to a single DB round-trip.
	"""
	frappe.db.sql(
		"UPDATE `tabSerial No` SET name = %s, serial_no = %s WHERE name = %s",
		(internal_serial, internal_serial, mfr_serial),
	)
	frappe.clear_document_cache("Serial No", mfr_serial)
	# Update global search: rename the existing row (if present).
	frappe.db.sql(
		"""UPDATE `__global_search`
		   SET name = %s, content = %s
		   WHERE doctype = 'Serial No' AND name = %s""",
		(internal_serial, f"{internal_serial} {mfr_serial} {item_code}", mfr_serial),
	)


def remap_serials_sabb(doc, method):
	"""
	Serial and Batch Bundle -- before_submit.

	Fires during the parent voucher's on_submit, after bundle entries are
	populated but before Stock Ledger Entries are written.

	Inward: renames every OEM-named Serial No to an internal serial, stores
	the OEM name in custom_mfr_ser, patches entries in-place.

	Outward: translates any OEM barcode values remaining in entries to the
	matching internal serial name (safety net for all transfer/consumption paths).
	"""
	if not frappe.get_cached_value("Item", doc.item_code, "custom_generate_internal_serial"):
		return

	if doc.type_of_transaction == "Outward":
		_translate_outward_entries(doc)
		return

	if doc.type_of_transaction != "Inward":
		return
	if doc.voucher_type not in INWARD_VOUCHERS:
		return

	# Resolve the series once — only needed for the fallback rename path.
	series = _get_series(doc.item_code)

	# Track MFR serials seen in this bundle to catch intra-bundle duplicates
	# before the idempotency DB check would silently merge them.
	seen_in_bundle = set()

	for entry in doc.entries:
		mfr_serial = entry.serial_no
		if not mfr_serial:
			continue

		if mfr_serial in seen_in_bundle:
			frappe.throw(
				f"MFR Serial <b>{mfr_serial}</b> appears more than once in this bundle for item "
				f"<b>{doc.item_code}</b>. Each manufacturer serial must be unique."
			)
		seen_in_bundle.add(mfr_serial)

		# Primary path: stub was already created with the internal name at scan time
		# (serial_batch.py stored mfr_serial in custom_mfr_ser).
		# Just update the bundle entry to point to the internal serial.
		already = frappe.db.get_value(
			"Serial No",
			{"custom_mfr_ser": mfr_serial, "item_code": doc.item_code},
			"name",
		)
		if already:
			_patch_entry(entry, already)
			continue

		# Skip entries that are already an internal serial (e.g. serial_batch.py
		# substituted the internal name for a re-receipt — entry.serial_no is
		# already correct, custom_mfr_ser already set on the Serial No doc).
		existing_mfr = frappe.db.get_value("Serial No", mfr_serial, "custom_mfr_ser")
		if existing_mfr:
			continue

		# Fallback: pre-existing OEM-named stub (from a cancelled PI or records
		# created before this app was deployed).  Rename it to an internal serial.
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

		internal_serial = _next_serial(series)

		if frappe.db.exists("Serial No", mfr_serial):
			_fast_rename_serial(mfr_serial, internal_serial, doc.item_code)
		else:
			frappe.db.sql(
				"""INSERT INTO `tabSerial No`
				   (name, serial_no, item_code, docstatus, creation, modified, owner, modified_by)
				   VALUES (%s, %s, %s, 0, NOW(), NOW(), %s, %s)""",
				(internal_serial, internal_serial, doc.item_code,
				 frappe.session.user, frappe.session.user),
			)

		frappe.db.set_value(
			"Serial No", internal_serial, "custom_mfr_ser", mfr_serial,
			update_modified=False,
		)
		_patch_entry(entry, internal_serial)


def _translate_outward_entries(doc):
	"""
	For Outward bundles: if any entry's serial_no is an OEM barcode value
	(not a valid Serial No name, but has a custom_mfr_ser → internal mapping),
	translate it to the internal name before SLEs are written.

	This is a safety net for all outward paths (Material Transfer, manufacturing
	consumption, Delivery Note, etc.) in case add_serial_batch_ledgers did not
	fully translate the entries.
	"""
	for entry in doc.entries:
		oem_value = entry.serial_no
		if not oem_value:
			continue
		# Already a valid internal serial name → nothing to do.
		if frappe.db.exists("Serial No", oem_value):
			continue
		# Look up internal serial by OEM mapping.
		internal = frappe.db.get_value(
			"Serial No",
			{"custom_mfr_ser": oem_value, "item_code": doc.item_code},
			"name",
		)
		if internal:
			_patch_entry(entry, internal)
		# If no mapping is found, leave as-is — the link validator will report
		# the real error (unknown serial) rather than masking it.


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


def translate_serial_nos_in_se(doc, method):
	"""
	Stock Entry -- validate.

	Translates OEM values in the `serial_no` text field of every Stock Entry
	Detail row for opted-in items.  This field is auto-populated by Work Orders
	and manufacturing flows with whatever serial names are in `tabSerial No`.  If
	the user scanned OEM barcodes via the SABB dialog those serials were renamed
	to internal names (CA-XXXXXX), so the text field should hold internal names.
	But if it was populated before our app ran (or via a path that bypasses our
	overrides), it may still hold OEM values which fail Frappe Link validation.
	"""
	for row in doc.get("items") or []:
		if not row.serial_no:
			continue
		if not frappe.get_cached_value("Item", row.item_code, "custom_generate_internal_serial"):
			continue

		oem_serials = [s.strip() for s in row.serial_no.strip().splitlines() if s.strip()]
		translated = []
		changed = False
		for oem in oem_serials:
			if frappe.db.exists("Serial No", oem):
				# Serial No exists — but normalize case (MariaDB is case-insensitive,
				# so "J6WDA1003288" matches "j6wda1003288"; we want the exact DB name).
				canonical = frappe.db.get_value("Serial No", oem, "name") or oem
				if canonical != oem:
					changed = True
				translated.append(canonical)
			else:
				internal = frappe.db.get_value(
					"Serial No",
					{"custom_mfr_ser": oem, "item_code": row.item_code},
					"name",
				)
				if internal:
					translated.append(internal)
					changed = True
				else:
					# Unknown value — keep as-is; let ERPNext report the real error.
					translated.append(oem)

		if changed:
			row.serial_no = "\n".join(translated)


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
