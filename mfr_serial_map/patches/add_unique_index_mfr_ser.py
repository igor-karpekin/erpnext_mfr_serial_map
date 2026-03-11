# mfr_serial_map/patches/add_unique_index_mfr_ser.py
#
# Adds a composite unique index on (item_code, custom_mfr_ser) to tabSerial No.
#
# In MariaDB/MySQL, NULL values are never considered equal in a UNIQUE index,
# so rows where custom_mfr_ser IS NULL (i.e. non-opted items) do not conflict.
# Only non-NULL values are enforced to be unique per item_code.
#
# The IF NOT EXISTS guard makes this patch safe to re-run.

import frappe


def execute():
	# Check whether the column exists at all (it may not if fixtures haven't
	# been applied yet — though normally patches run after migrate which applies
	# fixtures; adding a graceful skip just in case).
	columns = frappe.db.sql("SHOW COLUMNS FROM `tabSerial No` LIKE 'custom_mfr_ser'")
	if not columns:
		frappe.log_error(
			"add_unique_index_mfr_ser: column custom_mfr_ser not found on tabSerial No — "
			"ensure fixtures are applied before this patch.",
			"mfr_serial_map patch skipped",
		)
		return

	# Drop any pre-existing index of the same name so the CREATE is idempotent.
	existing = frappe.db.sql(
		"""SELECT INDEX_NAME FROM information_schema.STATISTICS
		   WHERE TABLE_SCHEMA = DATABASE()
		     AND TABLE_NAME   = 'tabSerial No'
		     AND INDEX_NAME   = 'unique_item_mfr_ser'"""
	)
	if existing:
		frappe.db.sql("ALTER TABLE `tabSerial No` DROP INDEX `unique_item_mfr_ser`")

	frappe.db.sql(
		"""ALTER TABLE `tabSerial No`
		   ADD UNIQUE INDEX `unique_item_mfr_ser` (item_code, custom_mfr_ser)"""
	)

	frappe.db.commit()
