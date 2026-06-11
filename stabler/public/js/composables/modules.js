import { t } from "./i18n.js";

/**
 * Canonical SPA module catalog — single source of truth for all module keys
 * and their human-readable labels.
 *
 * Keep this in sync with organization.py:_MODULE_ROLES / MODULE_KEYS.
 * Used by the per-user module override drawer (admin/Users.vue).
 * Note: Companies.vue has its own local moduleOptions (company toggles only),
 * so adding "dashboard" here does NOT create a dead company-toggle entry.
 *
 * "dashboard" is a virtual module: no company enable_* field, controlled only
 * by the per-user override / _MODULE_ROLES map. It must stay first so the
 * override drawer lists it prominently.
 */
export const MODULE_CATALOG = [
	{ key: "dashboard", label: t("Dashboard") },
	{ key: "money", label: t("Money") },
	{ key: "sales", label: t("Sales") },
	{ key: "purchasing", label: t("Purchasing") },
	{ key: "inventory", label: t("Inventory") },
	{ key: "manufacturing", label: t("Manufacturing") },
	{ key: "hr", label: t("HR") },
	{ key: "stock_reservation", label: t("Stock Reservation") },
	{ key: "compliance", label: t("Compliance") },
	{ key: "field_sales", label: t("Field Sales") },
	{ key: "marketing", label: t("Marketing") },
	{ key: "crm", label: t("CRM") },
	{ key: "service", label: t("Service") },
	{ key: "bpm", label: t("Processes") },
	{ key: "remittance", label: t("Remittance") },
	{ key: "installment", label: t("Installment") },
];
