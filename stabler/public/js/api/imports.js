import { call } from "./client.js";

const P = "stabler.api.imports";

export const importsApi = {
	home: (company) => call(`${P}.imports_home`, { company }),
	advanceAging: (company) => call(`${P}.import_advance_aging`, { company }),

	// Import Orders (native Purchase Order + imports custom fields, WP8)
	listImportOrders: (params) => call(`${P}.list_import_orders`, params),
	getImportOrder: (name) => call(`${P}.get_import_order`, { name }),
	createImportOrder: (payload) => call(`${P}.create_import_order`, payload),
	updateImportOrder: (payload) => call(`${P}.update_import_order`, payload),
	submitImportOrder: (name) => call(`${P}.submit_import_order`, { name }),
	// Accepts either a bare company string (legacy call sites) or a params
	// object { company, search } — PI Groups list page needs server-side search.
	listPiGroups: (companyOrParams) => {
		const params = typeof companyOrParams === "string" ? { company: companyOrParams } : (companyOrParams || {});
		return call(`${P}.list_pi_groups`, params);
	},
	createPiGroup: (payload) => call(`${P}.create_pi_group`, payload),
	piGroupDetail: (name) => call(`${P}.pi_group_detail`, { name }),
	savePiGroup: (payload, company) => call(`${P}.save_pi_group`, { payload, company }),
	deletePiGroup: (name, company) => call(`${P}.delete_pi_group`, { name, company }),
	listGroupEligiblePis: (group, company) => call(`${P}.list_group_eligible_pis`, { group, company }),
	assignPisToGroup: (group, pi_names, company) => call(`${P}.assign_pis_to_group`, { group, pi_names, company }),
	createAdvancePayment: (payload) => call(`${P}.create_advance_payment`, payload),

	// Commercial Invoices
	listCommercialInvoices: (params) => call(`${P}.list_commercial_invoices`, params),
	getCommercialInvoice: (name) => call(`${P}.get_commercial_invoice`, { name }),
	createCommercialInvoice: (payload) => call(`${P}.create_commercial_invoice`, payload),
	updateCommercialInvoice: (payload) => call(`${P}.update_commercial_invoice`, payload),
	setCiStatus: (name, status, reason) =>
		call(`${P}.set_ci_status`, { name, status, reason }),
	computeCustomsFee: (params) => call(`${P}.compute_customs_fee`, params),
	calculateCiLandedCostUzs: (commercial_invoice, exchange_rate, allocation_method) =>
		call(`${P}.calculate_ci_landed_cost_uzs`, { commercial_invoice, exchange_rate, allocation_method }),

	// Import Containers
	listImportContainers: (params) => call(`${P}.list_import_containers`, params),
	getImportContainer: (name) => call(`${P}.get_import_container`, { name }),
	createImportContainer: (payload) => call(`${P}.create_import_container`, payload),
	updateImportContainer: (payload) => call(`${P}.update_import_container`, payload),
	setContainerStatus: (name, status, reason) =>
		call(`${P}.set_container_status`, { name, status, reason }),
	toggleCostLineInclude: (container, row_name, include) =>
		call(`${P}.toggle_cost_line_include`, { container, row_name, include }),

	// Import Trucks
	listImportTrucks: (params) => call(`${P}.list_import_trucks`, params),
	getImportTruck: (name) => call(`${P}.get_import_truck`, { name }),
	createImportTruck: (payload) => call(`${P}.create_import_truck`, payload),
	updateImportTruck: (payload) => call(`${P}.update_import_truck`, payload),
	setTruckStatus: (name, status, reason) =>
		call(`${P}.set_truck_status`, { name, status, reason }),

	// Customs Declarations (GTD)
	listCustomsDeclarations: (params) => call(`${P}.list_customs_declarations`, params),
	getCustomsDeclaration: (name) => call(`${P}.get_customs_declaration`, { name }),
	createCustomsDeclaration: (payload) => call(`${P}.create_customs_declaration`, payload),
	updateCustomsDeclaration: (payload) => call(`${P}.update_customs_declaration`, payload),
	setCustomsDeclarationStatus: (name, status, reason) =>
		call(`${P}.set_customs_declaration_status`, { name, status, reason }),

	// Freight Bookings
	listFreightBookings: (params) => call(`${P}.list_freight_bookings`, params),
	getFreightBooking: (name) => call(`${P}.get_freight_booking`, { name }),
	createFreightBooking: (payload) => call(`${P}.create_freight_booking`, payload),
	updateFreightBooking: (payload) => call(`${P}.update_freight_booking`, payload),
	setFreightBookingStatus: (name, status, reason) =>
		call(`${P}.set_freight_booking_status`, { name, status, reason }),

	// Import Expenses
	listImportExpenses: (params) => call(`${P}.list_import_expenses`, params),
	getImportExpense: (name) => call(`${P}.get_import_expense`, { name }),
	createImportExpense: (payload) => call(`${P}.create_import_expense`, payload),
	updateImportExpense: (payload) => call(`${P}.update_import_expense`, payload),
	setExpenseLandedCost: (import_expense, cost_component) =>
		call(`${P}.set_expense_landed_cost`, { import_expense, cost_component }),
	clearExpenseLandedCost: (import_expense) =>
		call(`${P}.clear_expense_landed_cost`, { import_expense }),

	// Landed Cost Review
	getLandedCostReview: (grn_checklist, rate) =>
		call(`${P}.get_landed_cost_review`, { grn_checklist, rate }),
	submitLandedCostVoucher: (name) =>
		call("stabler.stabler.api.lcv.submit_landed_cost_voucher", { name }),


	// Container cost ledger + landed-cost bills (WP7 vendor traceability)
	containerCostLedger: (container) => call(`${P}.container_cost_ledger`, { container }),
	listLandedCostBills: (params) => call(`${P}.list_landed_cost_bills`, params),
	supplierLandedCostSummary: (company) => call(`${P}.supplier_landed_cost_summary`, { company }),

	// GRN Checklists
	listGrnChecklists: (params) => call(`${P}.list_grn_checklists`, params),
	getGrnChecklist: (name) => call(`${P}.get_grn_checklist`, { name }),
	createGrnForCi: (commercial_invoice) => call(`${P}.create_grn_for_ci`, { commercial_invoice }),
	refreshGrnExpectedQuantities: (name) => call(`${P}.refresh_grn_expected_quantities`, { name }),
	submitGrnChecklist: (name) => call(`${P}.submit_grn_checklist`, { name }),
	createAdditionalLcv: (grn_name) => call(`${P}.create_additional_lcv`, { grn_name }),

	// Truck Receipts
	listTruckReceipts: (params) => call(`${P}.list_truck_receipts`, params),
	getTruckReceipt: (name) => call(`${P}.get_truck_receipt`, { name }),
	createTruckReceipt: (payload) => call(`${P}.create_truck_receipt`, payload),
	updateTruckReceipt: (payload) => call(`${P}.update_truck_receipt`, payload),
	submitTruckReceipt: (name) => call(`${P}.submit_truck_receipt`, { name }),
	trucksPendingReceipt: (company, grn) => call(`${P}.trucks_pending_receipt`, { company, grn }),

	// Vet Certificates
	listVetCertificates: (params) => call(`${P}.list_vet_certificates`, params),
	createVetCertificate: (payload) => call(`${P}.create_vet_certificate`, payload),
	setVetCertificateStatus: (name, status, reason) =>
		call(`${P}.set_vet_certificate_status`, { name, status, reason }),

	// Hand-linking a transport / service bill to a Commercial Invoice (W1/W2).
	// Attribution only — these never capitalize a cost. Every rule lives on the
	// server; a client-side check here is a hint, never the gate.
	setBillImportRefs: (payload) => call(`${P}.set_bill_import_refs`, payload),
	clearBillImportRefs: (purchase_invoice) =>
		call(`${P}.clear_bill_import_refs`, { purchase_invoice }),
	unlinkedTransportBills: (commercial_invoice) =>
		call(`${P}.unlinked_transport_bills`, { commercial_invoice }),
	billImportLinkState: (purchase_invoice) =>
		call(`${P}.bill_import_link_state`, { purchase_invoice }),

	// Month-end accrual + channel payment calendar (WP-I14 / WP-I16)
	unbilledLandedCosts: (company) => call(`${P}.unbilled_landed_costs`, { company }),
	paymentCalendar: (company, days = 30) => call(`${P}.payment_calendar`, { company, days }),
};
