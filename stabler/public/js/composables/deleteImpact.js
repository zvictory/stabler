/**
 * Rendering the deletion impact report of a Proforma / Commercial Invoice.
 *
 * The server classifies the links but does not phrase them: the rule module
 * (`stabler/api/_imports_delete.py`) is Frappe-free and cannot translate, so it
 * returns a stable `code` per blocker. The sentence lives here — in one place,
 * so the two forms that show this report can never drift apart.
 *
 * Every blocker also gets a link to the screen that RESOLVES it. A doctype
 * without a Stabler screen renders as plain text; linking out to the Frappe
 * Desk is not an option.
 */
import { t } from "./i18n.js";

const RECORD_ROUTES = {
	"Purchase Invoice": "/purchasing/invoices/",
	"Payment Entry": "/money/payments/",
	"GRN Checklist": "/imports/grn-checklists/",
	"Customs Declaration": "/imports/customs/",
	"Proforma Invoice": "/imports/proformas/",
	"Import Container": "/imports/containers/",
	"Import Truck": "/imports/trucks/",
	"Commercial Invoice": "/imports/commercial-invoices/",
};

export function recordRoute(doctype, name) {
	const prefix = RECORD_ROUTES[doctype];
	return prefix && name ? prefix + encodeURIComponent(name) : null;
}

export function doctypeLabel(doctype) {
	switch (doctype) {
		case "Import Container":
			return t("Container");
		case "Import Truck":
			return t("Truck");
		case "Freight Booking":
			return t("Freight booking");
		case "Vet Certificate":
			return t("Veterinary certificate");
		case "Commercial Invoice PO Link":
			return t("Purchase order link");
		case "GRN Checklist":
			return t("GRN checklist");
		case "Commercial Invoice":
			return t("Commercial invoice");
		case "Commercial Invoice Item":
			return t("Commercial invoice line");
		case "Purchase Invoice":
			return t("Purchase invoice");
		case "Payment Entry":
			return t("Payment");
		case "Landed Cost Voucher":
			return t("Landed cost voucher");
		case "Customs Declaration":
			return t("Customs declaration");
		case "Proforma Invoice":
			return t("Proforma");
		case "Import Expense":
			return t("Import expense");
		default:
			return doctype;
	}
}

export function blockerText(b) {
	const name = b?.name || "";
	switch (b?.code) {
		case "live_payable":
			return t("Purchase invoice {name} is not cancelled — a live payable sits on the ledger. Cancel the invoice first.", { name });
		case "live_payment":
			return t("Payment {name} is not cancelled — money is already booked against this document. Cancel the payment first.", { name });
		case "landed_cost":
			return t("Landed cost voucher {name} is not cancelled — landed cost is spread over stock. Cancel it first.", { name });
		case "stock_received":
			return t("GRN checklist {name} is submitted — stock was received. Cancel it first.", { name });
		case "customs_declared":
			return t("Customs declaration {name} exists — an official declaration is never deleted from here.", { name });
		case "linked_proforma":
			return t("Proforma {name} is still superseded by this invoice — remove the link first.", { name });
		default:
			// Fail-closed on the server produces this for any doctype the rules
			// do not know; keep its own wording rather than inventing one.
			return t("{doctype} {name} is linked and has no deletion rule — resolve it manually first.", {
				doctype: doctypeLabel(b?.doctype),
				name,
			});
	}
}

/** Cascade rows as a flat, itemised list — what actually happens, per record. */
export function cascadeRows(plan) {
	const cascade = plan?.cascade || {};
	const modes = plan?.cascade_modes || {};
	return Object.keys(cascade).map((doctype) => ({
		doctype,
		label: doctypeLabel(doctype),
		detach: modes[doctype] === "detach",
		names: cascade[doctype] || [],
	}));
}
