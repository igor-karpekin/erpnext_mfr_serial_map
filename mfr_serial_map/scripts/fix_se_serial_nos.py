"""
mfr_serial_map/scripts/fix_se_serial_nos.py

One-time data-fix script: translates OEM serial values in the `serial_no`
text field of Stock Entry Detail rows to their internal mapped names.

Targets draft (docstatus=0) rows only — submitted entries have already
had SLEs written, fixing them here would not help (the SABB is already
submitted and cannot be changed this way).

Run on the server:
    bench --site <site> execute \
      "from mfr_serial_map.scripts.fix_se_serial_nos import fix_all; fix_all()"

Or for a dry run (no DB writes):
    bench --site <site> execute \
      "from mfr_serial_map.scripts.fix_se_serial_nos import fix_all; fix_all(dry_run=True)"
"""

import frappe


def fix_all(dry_run=False):
    # Find all draft Stock Entry Detail rows for opted-in items that have
    # a non-empty serial_no text field.
    rows = frappe.db.sql(
        """
        SELECT sed.name, sed.item_code, sed.serial_no, sed.parent
        FROM `tabStock Entry Detail` sed
        JOIN `tabStock Entry` se ON se.name = sed.parent
        WHERE se.docstatus = 0
          AND sed.serial_no IS NOT NULL
          AND sed.serial_no != ''
          AND sed.item_code IN (
              SELECT name FROM `tabItem` WHERE custom_generate_internal_serial = 1
          )
        """,
        as_dict=True,
    )

    if not rows:
        print("No draft Stock Entry Detail rows found for opted-in items.")
        return

    print(f"Found {len(rows)} rows to inspect.")
    changed = 0

    for row in rows:
        oem_serials = [s.strip() for s in row.serial_no.strip().splitlines() if s.strip()]
        translated = []
        row_changed = False

        for oem in oem_serials:
            if frappe.db.exists("Serial No", oem):
                # Already an internal name — keep as-is.
                translated.append(oem)
            else:
                internal = frappe.db.get_value(
                    "Serial No",
                    {"custom_mfr_ser": oem, "item_code": row.item_code},
                    "name",
                )
                if internal:
                    print(
                        f"  [{row.parent}] SED {row.name}: {oem!r} → {internal!r}"
                    )
                    translated.append(internal)
                    row_changed = True
                else:
                    print(
                        f"  [{row.parent}] SED {row.name}: {oem!r} — no mapping found, leaving as-is"
                    )
                    translated.append(oem)

        if row_changed:
            new_value = "\n".join(translated)
            if not dry_run:
                frappe.db.sql(
                    "UPDATE `tabStock Entry Detail` SET serial_no = %s, modified = NOW() WHERE name = %s",
                    (new_value, row.name),
                )
            changed += 1

    if not dry_run:
        frappe.db.commit()
        print(f"\nDone. Updated {changed} rows.")
    else:
        print(f"\nDry run complete. Would update {changed} rows (no changes written).")
