# mfr_serial_map/overrides/inward_before_submit.py
#
# Runs in the before_submit window of inward vouchers (Purchase Receipt,
# Purchase Invoice with Update Stock, Stock Entry for inward purposes).
#
# At that point the Serial and Batch Bundle exists as a draft and its entries
# hold the manufacturer serial values scanned by the user.  No Stock Ledger
# Entries have been written yet, so renaming Serial No documents is safe.
#
# After this hook completes the bundle entries carry the internal serials;
# the upstream on_submit flow writes SLEs against those internal serials,
# which is what every downstream report, reservation and valuation expects.

import frappe
from frappe.model.naming import make_autoname
from frappe.model.rename_doc import rename_doc


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


def _remap_bundle(bundle_name, item_code):
	"""
	For every entry in the SABB whose serial_no does not yet have a
	custom_mfr_ser value (i.e. it still carries the scanned manufacturer
	serial as its name):

	  1. Determine the next internal serial via Item series or Document Naming Rule.
	  2. rename_doc: Serial No <mfr_serial> → <internal_serial>.
	  3. Write custom_mfr_ser = <mfr_serial> on the renamed record.
	  4. Update the global-search index row.
	  5. Patch entry.serial_no = <internal_serial> and save the bundle.

	Idempotent: if a Serial No with custom_mfr_ser = mfr_serial already
	exists for this item the entry is updated to point to it and skipped.
	"""
	bundle = frappe.get_doc("Serial and Batch Bundle", bundle_name)
	changed = False

	for entry in bundle.entries:
		mfr_serial = entry.serial_no
		if not mfr_serial:
			continue

		# Idempotency guard: already remapped in a previous attempt.
		already = frappe.db.get_value(
			"Serial No",
			{"custom_mfr_ser": mfr_serial, "item_code": item_code},
			"name",
		)
		if already:
			if entry.serial_no != already:
				entry.serial_no = already
				changed = True
			continue

		# Uniqueness guard: catches concurrent submissions.
		conflict = frappe.db.get_value(
			"Serial No",
			{"custom_mfr_ser": mfr_serial, "item_code": item_code},
			"name",
		)
		if conflict:
			frappe.throw(
				f"MFR Serial <b>{mfr_serial}</b> already exists for item "
				f"<b>{item_code}</b> as internal serial <b>{conflict}</b>. "
				f"Each manufacturer serial must be unique per item."
			)

		internal_serial = _get_next_internal_serial(item_code)

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
			# Fallback: CSV/bulk-upload path — create fresh with internal name.
			sn = frappe.new_doc("Serial No")
			sn.serial_no = internal_serial
			sn.item_code = item_code
			sn.flags.ignore_permissions = True
			sn.insert(ignore_permissions=True)

		# Single source of truth for the manufacturer serial.
		# db.set_value is intentional here — we do NOT want validate/save hooks
		# to fire again at this point.
		frappe.db.set_value("Serial No", internal_serial, "custom_mfr_ser", mfr_serial)

		# Keep the full-text global search index in sync.
		# frappe.db.set_value bypasses the document lifecycle, so there is no
		# on_update event to trigger the index rebuild; we do it explicitly.
		frappe.db.sql(
			"""UPDATE `__global_search`
			   SET content = %s
			   WHERE doctype = 'Serial No' AND name = %s""",
			(f"{internal_serial} {mfr_serial} {item_code}", internal_serial),
		)

		entry.serial_no = internal_serial
		changed = True

	if changed:
		bundle.flags.ignore_validate = True
		bundle.flags.ignore_permissions = True
		bundle.save()

	return changed


def _process_items(items):
	"""Walk the items table and remap every applicable SABB."""
	for item in items:
		if not item.get("serial_and_batch_bundle"):
			continue
		if not frappe.get_cached_value("Item", item.item_code, "has_serial_no"):
			continue
		if not frappe.get_cached_value("Item", item.item_code, "custom_generate_internal_serial"):
			continue
		_remap_bundle(item.serial_and_batch_bundle, item.item_code)


# ── event handlers ─────────────────────────────────────────────────────────────

def remap_serials(doc, method):
	"""Purchase Receipt — always has stock impact."""
	_process_items(doc.items)


def remap_serials_pi(doc, method):
	"""Purchase Invoice — only when 'Update Stock' is ticked."""
	if doc.update_stock:
		_process_items(doc.items)


def remap_serials_se(doc, method):
	"""Stock Entry — only for inward purposes."""
	INWARD_PURPOSES = {"Material Receipt", "Manufacture", "Repack"}
	if doc.purpose not in INWARD_PURPOSES:
		return
	_process_items(doc.items)
