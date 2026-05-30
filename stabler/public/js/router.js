import { createRouter, createWebHashHistory } from "vue-router";
import { useSession } from "./stores/session.js";
import Dashboard from "./pages/Dashboard.vue";
import Module from "./pages/Module.vue";
import MoneyHome from "./pages/money/MoneyHome.vue";
import Accounts from "./pages/money/Accounts.vue";
import JournalEntries from "./pages/money/JournalEntries.vue";
import PaymentEntries from "./pages/money/PaymentEntries.vue";
import Expenses from "./pages/money/Expenses.vue";
import Transfers from "./pages/money/Transfers.vue";
import Reports from "./pages/money/Reports.vue";
import SalesHome from "./pages/sales/SalesHome.vue";
import Customers from "./pages/sales/Customers.vue";
import Quotations from "./pages/sales/Quotations.vue";
import SalesOrders from "./pages/sales/SalesOrders.vue";
import SalesInvoices from "./pages/sales/SalesInvoices.vue";
import SalesAging from "./pages/sales/Aging.vue";
import InvoicePrint from "./pages/sales/InvoicePrint.vue";
import PurchasingHome from "./pages/purchasing/PurchasingHome.vue";
import Suppliers from "./pages/purchasing/Suppliers.vue";
import PurchaseInvoices from "./pages/purchasing/PurchaseInvoices.vue";
import PurchasingAging from "./pages/purchasing/Aging.vue";
import InventoryHome from "./pages/inventory/InventoryHome.vue";
import Items from "./pages/inventory/Items.vue";
import Warehouses from "./pages/inventory/Warehouses.vue";
import StockLedger from "./pages/inventory/StockLedger.vue";
import StockEntries from "./pages/inventory/StockEntries.vue";
import LowStockAlerts from "./pages/inventory/LowStockAlerts.vue";
import ManufacturingHome from "./pages/manufacturing/ManufacturingHome.vue";
import BOMs from "./pages/manufacturing/BOMs.vue";
import WorkOrders from "./pages/manufacturing/WorkOrders.vue";
import HRHome from "./pages/hr/HRHome.vue";
import Employees from "./pages/hr/Employees.vue";
import HROrgChart from "./pages/hr/OrgChart.vue";
import HRAttendance from "./pages/hr/Attendance.vue";
import LeaveApplications from "./pages/hr/LeaveApplications.vue";
import Payroll from "./pages/hr/Payroll.vue";
import SFAHome from "./pages/sfa/SFAHome.vue";
import Outlets from "./pages/sfa/Outlets.vue";
import Routes from "./pages/sfa/Routes.vue";
import Visits from "./pages/sfa/Visits.vue";
import FieldUsers from "./pages/sfa/FieldUsers.vue";
import VanStock from "./pages/sfa/VanStock.vue";
import Promos from "./pages/sfa/Promos.vue";
import Photos from "./pages/sfa/Photos.vue";
import Planograms from "./pages/sfa/Planograms.vue";
import OSA from "./pages/sfa/OSA.vue";
import Receivables from "./pages/sfa/Receivables.vue";
import MarketingHome from "./pages/marketing/MarketingHome.vue";
import PromoPlans from "./pages/marketing/PromoPlans.vue";
import ROI from "./pages/marketing/ROI.vue";
import Claims from "./pages/marketing/Claims.vue";
import Equipment from "./pages/marketing/Equipment.vue";
import RepairRequests from "./pages/marketing/RepairRequests.vue";
import AdminHome from "./pages/admin/AdminHome.vue";
import AdminUsers from "./pages/admin/Users.vue";
import AdminRoles from "./pages/admin/Roles.vue";
import AdminCompanies from "./pages/admin/Companies.vue";
import AdminCompliance from "./pages/admin/Compliance.vue";
import NotFound from "./pages/NotFound.vue";
import ServerError from "./pages/ServerError.vue";

const routes = [
	{ path: "/", redirect: "/dashboard" },
	{ path: "/dashboard", name: "dashboard", component: Dashboard, meta: { title: "Dashboard" } },
	{
		path: "/money",
		component: MoneyHome,
		meta: { title: "Money", module: "money" },
		children: [
			{ path: "", redirect: "/money/accounts" },
			{ path: "accounts", name: "money-accounts", component: Accounts, meta: { title: "Chart of Accounts" } },
			{ path: "journals", name: "money-journals", component: JournalEntries, meta: { title: "Journal Entries" } },
			{ path: "payments", name: "money-payments", component: PaymentEntries, meta: { title: "Payments" } },
			{ path: "expenses", name: "money-expenses", component: Expenses, meta: { title: "Expenses" } },
			{ path: "transfers", name: "money-transfers", component: Transfers, meta: { title: "Transfers" } },
			{ path: "reports", name: "money-reports", component: Reports, meta: { title: "Reports" } },
		],
	},
	{
		path: "/sales",
		component: SalesHome,
		meta: { title: "Sales", module: "sales" },
		children: [
			{ path: "", redirect: "/sales/customers" },
			{ path: "customers", name: "sales-customers", component: Customers, meta: { title: "Customers" } },
			{ path: "quotations", name: "sales-quotations", component: Quotations, meta: { title: "Quotations" } },
			{ path: "orders", name: "sales-orders", component: SalesOrders, meta: { title: "Sales Orders" } },
			{ path: "invoices", name: "sales-invoices", component: SalesInvoices, meta: { title: "Sales Invoices" } },
			{ path: "invoices/:name/print", name: "sales-invoice-print", component: InvoicePrint, meta: { title: "Invoice" } },
			{ path: "aging", name: "sales-aging", component: SalesAging, meta: { title: "AR Aging" } },
		],
	},
	{
		path: "/purchasing",
		component: PurchasingHome,
		meta: { title: "Purchasing", module: "purchasing" },
		children: [
			{ path: "", redirect: "/purchasing/suppliers" },
			{ path: "suppliers", name: "purchasing-suppliers", component: Suppliers, meta: { title: "Suppliers" } },
			{ path: "invoices", name: "purchasing-invoices", component: PurchaseInvoices, meta: { title: "Purchase Invoices" } },
			{ path: "aging", name: "purchasing-aging", component: PurchasingAging, meta: { title: "AP Aging" } },
		],
	},
	{
		path: "/inventory",
		component: InventoryHome,
		meta: { title: "Inventory", module: "inventory" },
		children: [
			{ path: "", redirect: "/inventory/items" },
			{ path: "items", name: "inventory-items", component: Items, meta: { title: "Items" } },
			{ path: "warehouses", name: "inventory-warehouses", component: Warehouses, meta: { title: "Warehouses" } },
			{ path: "entries", name: "inventory-entries", component: StockEntries, meta: { title: "Stock Entries" } },
			{ path: "ledger", name: "inventory-ledger", component: StockLedger, meta: { title: "Stock Ledger" } },
			{ path: "alerts", name: "inventory-alerts", component: LowStockAlerts, meta: { title: "Low Stock Alerts" } },
		],
	},
	{
		path: "/manufacturing",
		component: ManufacturingHome,
		meta: { title: "Manufacturing", module: "manufacturing" },
		children: [
			{ path: "", redirect: "/manufacturing/boms" },
			{ path: "boms", name: "manufacturing-boms", component: BOMs, meta: { title: "BOMs" } },
			{ path: "work-orders", name: "manufacturing-work-orders", component: WorkOrders, meta: { title: "Work Orders" } },
		],
	},
	{
		path: "/hr",
		component: HRHome,
		meta: { title: "People", module: "hr" },
		children: [
			{ path: "", redirect: "/hr/employees" },
			{ path: "employees", name: "hr-employees", component: Employees, meta: { title: "Employees" } },
			{ path: "org", name: "hr-org", component: HROrgChart, meta: { title: "Positions" } },
			{ path: "attendance", name: "hr-attendance", component: HRAttendance, meta: { title: "Attendance" } },
			{ path: "leave", name: "hr-leave", component: LeaveApplications, meta: { title: "Leave" } },
			{ path: "payroll", name: "hr-payroll", component: Payroll, meta: { title: "Payroll" } },
		],
	},
	{
		path: "/sfa",
		component: SFAHome,
		meta: { title: "Field Sales", module: "field_sales" },
		children: [
			{ path: "", redirect: "/sfa/outlets" },
			{ path: "outlets", name: "sfa-outlets", component: Outlets, meta: { title: "Outlets" } },
			{ path: "routes", name: "sfa-routes", component: Routes, meta: { title: "Routes" } },
			{ path: "visits", name: "sfa-visits", component: Visits, meta: { title: "Visits" } },
			{ path: "field-users", name: "sfa-field-users", component: FieldUsers, meta: { title: "Field Users" } },
			{ path: "van-stock", name: "sfa-van-stock", component: VanStock, meta: { title: "Van Stock" } },
			{ path: "promos", name: "sfa-promos", component: Promos, meta: { title: "Promos" } },
			{ path: "photos", name: "sfa-photos", component: Photos, meta: { title: "Photos" } },
			{ path: "planograms", name: "sfa-planograms", component: Planograms, meta: { title: "Planograms" } },
			{ path: "osa", name: "sfa-osa", component: OSA, meta: { title: "OSA Audits" } },
			{ path: "receivables", name: "sfa-receivables", component: Receivables, meta: { title: "Receivables" } },
		],
	},
	{
		path: "/marketing",
		component: MarketingHome,
		meta: { title: "Trade Marketing", module: "marketing" },
		children: [
			{ path: "", redirect: "/marketing/plans" },
			{ path: "plans", name: "marketing-plans", component: PromoPlans, meta: { title: "Promo Plans" } },
			{ path: "roi", name: "marketing-roi", component: ROI, meta: { title: "Campaign ROI" } },
			{ path: "claims", name: "marketing-claims", component: Claims, meta: { title: "Claims" } },
			{ path: "equipment", name: "marketing-equipment", component: Equipment, meta: { title: "Equipment" } },
			{ path: "repairs", name: "marketing-repairs", component: RepairRequests, meta: { title: "Repair Requests" } },
		],
	},
	{
		path: "/admin",
		component: AdminHome,
		meta: { title: "Admin", requiresAdmin: true },
		children: [
			{ path: "", redirect: "/admin/users" },
			{ path: "users", name: "admin-users", component: AdminUsers, meta: { title: "Users" } },
			{ path: "roles", name: "admin-roles", component: AdminRoles, meta: { title: "Roles" } },
			{ path: "companies", name: "admin-companies", component: AdminCompanies, meta: { title: "Companies" } },
			{ path: "compliance", name: "admin-compliance", component: AdminCompliance, meta: { title: "Compliance" } },
		],
	},
	{ path: "/error", name: "server-error", component: ServerError, meta: { title: "Error" } },
	{ path: "/:pathMatch(.*)*", name: "not-found", component: NotFound, meta: { title: "Not found" } },
];

export const router = createRouter({
	history: createWebHashHistory(),
	routes,
});

router.beforeEach((to) => {
	const session = useSession();
	if (to.matched.some((r) => r.meta.requiresAdmin) && !session.isAdmin) {
		return { name: "dashboard" };
	}
	const moduleRoute = to.matched.find((r) => r.meta.module);
	if (moduleRoute && !session.canAccessModule(moduleRoute.meta.module)) {
		return { name: "dashboard" };
	}
});

router.afterEach((to) => {
	const base = "Stabler";
	document.title = to.meta?.title ? `${to.meta.title} · ${base}` : base;
});
