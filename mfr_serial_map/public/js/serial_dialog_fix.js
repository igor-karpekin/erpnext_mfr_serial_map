// mfr_serial_map/public/js/serial_dialog_fix.js
//
// Fixes an ERPNext bug where the serial/batch selector dialog only opens for
// the first serialized item added to a transaction form per page load.
//
// Root cause (transaction.js - show_batch_dialog_if_required):
//   frappe.flags.dialog_set is set to true when the dialog opens, but is
//   never reset when the dialog closes — only when the dialog is *skipped*.
//   Every subsequent item_code trigger therefore sees dialog_set=true and
//   skips the dialog silently.
//
// Fix: extend SerialBatchPackageSelector to reset dialog_set on modal hide,
//   so the next item addition will open the dialog again.

frappe.after_ajax(function () {
	if (typeof erpnext === "undefined" || !erpnext.SerialBatchPackageSelector) {
		return;
	}

	const _Original = erpnext.SerialBatchPackageSelector;

	erpnext.SerialBatchPackageSelector = class extends _Original {
		make() {
			super.make();
			// Reset the guard flag when the modal fully disappears so that
			// adding the next serialized item will re-open the dialog.
			this.dialog.$wrapper.on("hidden.bs.modal", () => {
				frappe.flags.dialog_set = false;
			});
		}
	};
});
