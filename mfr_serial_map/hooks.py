app_name = "mfr_serial_map"
app_title = "MFR Serial Map"
app_publisher = "Your Company"
app_description = "Maps manufacturer serial numbers to ERPNext-generated internal serials"
app_version = "0.0.1"
app_email = "you@example.com"
app_license = "MIT"
app_icon = "octicon octicon-tag"

# Fixtures are synced on `bench migrate`
fixtures = ["Custom Field", "Property Setter"]

doctype_js = {
	"Item": "public/js/item_form.js",
}

# ── doc_events ────────────────────────────────────────────────────────────────
# SABB.before_submit fires during the parent voucher's on_submit, after the
# bundle entries are populated but before Stock Ledger Entries are written.
# This is the only reliable window for renaming Serial No documents, because
# for amended PIs (and in general) the SABB does not yet exist at
# Purchase Invoice.before_submit time.
doc_events = {
	"Serial No": {
		# Uniqueness of custom_mfr_ser per item_code — catches form edits,
		# imports and any non-receipt code path.
		"before_save": "mfr_serial_map.overrides.serial_no_validate.validate_mfr_ser_unique",
	},
	"Serial and Batch Bundle": {
		# Remap OEM serials → internal serials for all inward vouchers.
		"before_submit": "mfr_serial_map.overrides.inward_before_submit.remap_serials_sabb",
	},
}

# ── override_whitelisted_methods ───────────────────────────────────────────────
# Wraps upstream whitelist-exposed APIs without modifying core files.
override_whitelisted_methods = {
	# Form-level scan field (scan_barcode on the document header)
	"erpnext.stock.utils.scan_barcode":
		"mfr_serial_map.overrides.scan_barcode.scan_barcode",
	# Serial & Batch Bundle dialog scan field (one-by-one scan)
	"erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle.is_serial_batch_no_exists":
		"mfr_serial_map.overrides.serial_batch.is_serial_batch_no_exists",
	# Serial & Batch Bundle dialog manual entry (textarea / range / CSV upload)
	"erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle.create_serial_nos":
		"mfr_serial_map.overrides.serial_batch.create_serial_nos",
	# Translates OEM serial values → internal names in entries before SABB is
	# saved, so Frappe's Link field validation passes.
	"erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle.add_serial_batch_ledgers":
		"mfr_serial_map.overrides.serial_batch.add_serial_batch_ledgers",
}

# ── standard_queries ───────────────────────────────────────────────────────────
# Replaces the default Link-field autocomplete for Serial No so that users can
# search by name, item_code, OR custom_mfr_ser in every Link field in the system.
standard_queries = {
	"Serial No": "mfr_serial_map.overrides.serial_no_search.serial_no_query",
}
