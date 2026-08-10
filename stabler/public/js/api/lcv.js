import { call } from "./client.js";

export const lcvApi = {
	getLandedCostReview: (document_type, document_name, rate) =>
		call("stabler.stabler.api.lcv.get_landed_cost_review", {
			document_type,
			document_name,
			rate,
		}),

	toggleCostLineInclude: (document_type, document_name, container, row_name, include) =>
		call("stabler.stabler.api.lcv.toggle_cost_line_include", {
			document_type,
			document_name,
			container,
			row_name,
			include,
		}),

	createAdditionalLcv: (document_type, document_name) =>
		call("stabler.stabler.api.lcv.create_additional_lcv", {
			document_type,
			document_name,
		}),

	submitLandedCostVoucher: (name) =>
		call("stabler.stabler.api.lcv.submit_landed_cost_voucher", { name }),
};

