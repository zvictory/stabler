import { call } from "./client.js";

export const lcvApi = {
	getLandedCostReview: (document_type, document_name, rate) =>
		call("stabler.api.lcv.get_landed_cost_review", {
			document_type,
			document_name,
			rate,
		}),

	toggleCostLineInclude: (document_type, document_name, container, row_name, include) =>
		call("stabler.api.lcv.toggle_cost_line_include", {
			document_type,
			document_name,
			container,
			row_name,
			include,
		}),

	// Persists how the next voucher spreads its charges ("Qty" | "Amount").
	// Resolves to the same `distribution` object `getLandedCostReview` returns,
	// and throws when a submitted voucher has already frozen the basis — the
	// server is the gate, a disabled control is only the hint.
	setDistributionMethod: (document_type, document_name, method) =>
		call("stabler.api.lcv.set_distribution_method", {
			document_type,
			document_name,
			method,
		}),

	createAdditionalLcv: (document_type, document_name) =>
		call("stabler.api.lcv.create_additional_lcv", {
			document_type,
			document_name,
		}),

	submitLandedCostVoucher: (name) => call("stabler.api.lcv.submit_landed_cost_voucher", { name }),

	cancelLandedCostVoucher: (name) => call("stabler.api.lcv.cancel_landed_cost_voucher", { name }),
};
