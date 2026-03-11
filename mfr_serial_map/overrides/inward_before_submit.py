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
from frappe.model.rename_doc import rename_doc
from erpnext.stock.doctype.serial_no.serial_no import get_new_serial_number


def _remap_bundle(bundle_name, item_code):
	"""
	For every entry in the SABB whose serial_no does not yet have a
	custom_mfr_ser value (i.e. it still carries the scanned manufacturer
	serial as its name):

	  1. Generate a new internal serial via the item's Serial No Series.
	  2. rename_doc: Serial No <mfr_serial> → <internal_serial>.
	  3. Write custom_mfr_ser = <mfr_serial> on the renamed record.
	  4. Update the global-search index row (db.set_value bypasses hooks).
	  5. Patch entry.serial_no = <internal_serial> and save the bundle.

	Idempotent: re-running the function on an already-remapped bundle is a
	no-op because step 3 leaves a non-empty custom_mfr_ser, which is the
	guard checked at the top of the loop.
	"""
	series = frappe.get_cached_value("Item", item_code, "serial_no_series")
	if not series:
		frappe.throw(
			f"Item {frappe.bold(item_code)} has <b>Generate Internal Serial No</b> enabled "
			f"but no <b>Serial No Series</b> is defined on the item."
		)

	bundle = frappe.get_doc("Serial and Batch Bundle", bundle_name)
	changed = False

	for entry in bundle.entries:
		mfr_serial = entry.serial_no
		if not mfr_serial:
			continue

		# Idempotency guard: non-empty custom_mfr_ser means this entry was
		# already processed (the serial_no field now holds the internal name).
		if frappe.db.get_value("Serial No", mfr_serial, "custom_mfr_ser"):
			continue

		# Uniqueness guard: same MFR serial must not exist for the same item
		# under a different internal serial name.
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

		internal_serial = get_new_serial_number(series)

		if frappe.db.exists("Serial No", mfr_serial):
			# Standard path: Serial No was created by is_serial_batch_no_exists
			# at scan time inside the SABB dialog.
			rename_doc(
				"Serial No",
				mfr_serial,
				internal_serial,
				ignore_permissions=True,
				rebuild_search=False,  # we update the index manually below
			)
		else:
			# Fallback: CSV / bulk-upload path where Serial No may not exist yet.
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
