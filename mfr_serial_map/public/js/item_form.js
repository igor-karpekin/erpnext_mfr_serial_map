// mfr_serial_map/public/js/item_form.js
//
// Provides inline status feedback on the Item form for the
// "Generate Internal Serial No" checkbox.

frappe.ui.form.on("Item", {
	refresh(frm) {
		mfr_serial_map.update_serial_checkbox_status(frm);
	},

	has_serial_no(frm) {
		mfr_serial_map.update_serial_checkbox_status(frm);
	},

	custom_generate_internal_serial(frm) {
		mfr_serial_map.update_serial_checkbox_status(frm);
	},

	serial_no_series(frm) {
		mfr_serial_map.update_serial_checkbox_status(frm);
	},
});

window.mfr_serial_map = window.mfr_serial_map || {};

mfr_serial_map.update_serial_checkbox_status = function (frm) {
	const enabled = frm.doc.custom_generate_internal_serial;
	const series = (frm.doc.serial_no_series || "").trim();

	if (!enabled) {
		// Restore the original description when unchecked
		frm.set_df_property(
			"custom_generate_internal_serial",
			"description",
			__("When enabled, the manufacturer serial scanned at receipt is stored in MFR Serial No and the item\u2019s Serial No Series generates the internal tracking number.")
		);
		return;
	}

	if (series) {
		// Active and series is set directly on the item
		frm.set_df_property(
			"custom_generate_internal_serial",
			"description",
			`<span style="color:green">&#10003; Active &mdash; using series <b>${series}</b></span>`
		);
	} else {
		// Enabled but no item-level series — resolve from server (site default)
		frappe.call({
			method: "mfr_serial_map.overrides.inward_before_submit.get_effective_series",
			args: { item_code: frm.doc.name },
			callback(r) {
				if (r.message) {
					frm.set_df_property(
						"custom_generate_internal_serial",
						"description",
						`<span style="color:green">&#10003; Active &mdash; using site default series <b>${r.message}</b></span>`
					);
				} else {
					frm.set_df_property(
						"custom_generate_internal_serial",
						"description",
						`<span style="color:red">&#9888; Not active &mdash; no Serial No Series defined on this item and no site default configured. ` +
						`Set a series in <b>Serial Number Series</b> or via <b>Setup &rarr; Naming Series</b>.</span>`
					);
				}
			},
		});
	}
};
