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

# ── doc_events ────────────────────────────────────────────────────────────────
# Fires before the stock ledger is written — the only safe window to rename
# Serial No documents before any SLE references them.
doc_events = {
	"Serial No": {
		# Uniqueness of custom_mfr_ser per item_code — catches form edits,
		# imports and any non-receipt code path.
		"before_save": "mfr_serial_map.overrides.serial_no_validate.validate_mfr_ser_unique",
	},
	"Purchase Receipt": {
		"before_submit": "mfr_serial_map.overrides.inward_before_submit.remap_serials",
	},
	"Purchase Invoice": {
		# Only relevant when 'Update Stock' is ticked
		"before_submit": "mfr_serial_map.overrides.inward_before_submit.remap_serials_pi",
	},
	"Stock Entry": {
		# Only relevant for inward purposes (Material Receipt, Manufacture, Repack)
		"before_submit": "mfr_serial_map.overrides.inward_before_submit.remap_serials_se",
	},
}

# ── override_whitelisted_methods ───────────────────────────────────────────────
# Wraps upstream whitelist-exposed APIs without modifying core files.
override_whitelisted_methods = {
	# Form-level scan field (scan_barcode on the document header)
	"erpnext.stock.utils.scan_barcode":
		"mfr_serial_map.overrides.scan_barcode.scan_barcode",
	# Serial & Batch Bundle dialog scan field
	"erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle.is_serial_batch_no_exists":
		"mfr_serial_map.overrides.serial_batch.is_serial_batch_no_exists",
}

# ── standard_queries ───────────────────────────────────────────────────────────
# Replaces the default Link-field autocomplete for Serial No so that users can
# search by name, item_code, OR custom_mfr_ser in every Link field in the system.
standard_queries = {
	"Serial No": "mfr_serial_map.overrides.serial_no_search.serial_no_query",
}
