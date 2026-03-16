# MFR Serial Map

A Frappe/ERPNext custom app that transparently maps **manufacturer (OEM) serial numbers** to **internal sequential serials** during inward stock transactions.

When warehouse staff scan a manufacturer barcode (e.g. `0F2D33E9`), the system creates and uses an internal serial (e.g. `XYZ-12345678`) — silently and without modifying how the operator works.

---

## Why this exists

ERPNext uses the scanned barcode as the Serial No document name. For items received from multiple vendors, OEM serials are arbitrary strings with no consistent format and no guarantee of uniqueness across vendors. This app enforces a site-wide sequential naming convention while keeping the original OEM reference for traceability.

---

## How it works

### Custom fields

| Doctype | Field | Purpose |
|---|---|---|
| `Item` | `custom_generate_internal_serial` | Checkbox — opt this item in to the mapping |
| `Serial No` | `custom_mfr_ser` | Stores the original OEM serial for traceability |

### Hook 1 — at scan time (`serial_batch.py`)

Overrides `is_serial_batch_no_exists`, which fires on every barcode scan in the Serial & Batch Bundle dialog.

For opted-in items on inward transactions:

1. Generates the next internal serial (e.g. `XYZ-.########`) via the item's series or a Document Naming Rule.
2. Creates the `Serial No` stub with the **correct internal name** immediately via a direct SQL `INSERT` — no Frappe document layer, no `after_insert` hooks, no toast.
3. Stores the scanned OEM value in `custom_mfr_ser`.

The bundle entry (controlled by browser-side JS) continues to hold the raw scanned value — that is handled at submit time.

### Hook 2 — at submit time (`inward_before_submit.py`)

Hooked to `Serial and Batch Bundle.before_submit`, which fires inside `Purchase Invoice.on_submit` **after** bundle entries are populated but **before** Stock Ledger Entries are written.

For each bundle entry carrying an OEM serial:

1. Queries `Serial No` by `custom_mfr_ser = oem_serial` → finds the internal serial created at scan time.
2. Calls `_patch_entry` — a single `UPDATE` on `tabSerial and Batch Entry` plus an in-memory assignment on `entry.serial_no`.

The SLE writer then sees the internal serial name. No rename is performed.

### Fallback — pre-existing OEM stubs

For Serial No records created **before** this app was deployed (or from cancelled transactions), where `name = oem_serial` and `custom_mfr_ser` is not set: `_fast_rename_serial` performs a direct `UPDATE tabSerial No SET name = internal_serial` and updates `__global_search`. This bypasses `rename_doc`, which scans every doctype for Serial No link fields and costs ~2–3 s per serial.

---

## Performance

| Approach | Time for 20 serials | Toasts |
|---|---|---|
| `rename_doc` (v1) | ~60 s | "Document renamed" × 20 |
| `_fast_rename_serial` direct SQL (v2) | ~1–2 s | none |
| Create with correct name at scan time (current) | < 1 s | none |

The primary path at submit time is 20 `SELECT` + 20 `UPDATE` — no renames, no metadata scans.

---

## Supported voucher types

- Purchase Invoice
- Purchase Receipt
- Stock Entry (inward)

---

## Setup

### 1. Install

```bash
cd ~/frappe-bench
bench get-app mfr_serial_map <repo-url>
bench --site <your-site> install-app mfr_serial_map
bench --site <your-site> migrate
```

### 2. Configure the naming series

Either set **Serial Number Series** on the Item (e.g. `XYZ.#########`, `AA-.YY..MM..DD.-.####`), or create a **Document Naming Rule** for `Serial No` in ERPNext Setup to use the same format by default.

### 3. Enable per item

On each Item that should use internal serials, check **Generate Internal Serial No** (`custom_generate_internal_serial`).

To bulk-enable for all serialized items:

```sql
-- scripts/set_generate_internal_serial.sql
SET SQL_SAFE_UPDATES = 0;
UPDATE `tabItem`
SET    custom_generate_internal_serial = 1
WHERE  has_serial_no = 1;
SET SQL_SAFE_UPDATES = 1;
SELECT name, custom_generate_internal_serial
FROM   `tabItem`
WHERE  has_serial_no = 1;
```

---

## File structure

```
mfr_serial_map/
├── fixtures/
│   └── custom_field.json          # custom_mfr_ser, custom_generate_internal_serial
├── overrides/
│   ├── serial_batch.py            # Scan-time hook — creates stub with internal name
│   ├── inward_before_submit.py    # Submit-time hook — patches bundle entries
│   └── serial_no_validate.py     # Uniqueness validation on custom_mfr_ser
├── hooks.py
└── public/
    └── js/
        └── item_form.js           # UI helpers (series preview)
scripts/
└── set_generate_internal_serial.sql
```

---

## Traceability

Every internal serial carries the original OEM value in `custom_mfr_ser`. The field is visible on the Serial No form and searchable via ERPNext's global search.

---

## Compatibility

- ERPNext v16 / Frappe 16.x
