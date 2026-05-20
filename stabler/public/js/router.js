import { createRouter, createWebHashHistory } from "vue-router";
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
import HRAttendance from "./pages/hr/Attendance.vue";
import LeaveApplications from "./pages/hr/LeaveApplications.vue";
import Payroll from "./pages/hr/Payroll.vue";
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
		meta: { title: "Money" },
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
		meta: { title: "Sales" },
		children: [
			{ path: "", redirect: "/sales/customers" },
			{ path: "customers", name: "sales-customers", component: Customers, meta: { title: "Customers" } },
			{ path: "quotations", name: "sales-quotations", component: Quotations, meta: { title: "Quotations" } },
			{ path: "orders", name: "sales-orders", component: SalesOrders, meta: { title: "Sales Orders" } },
			{ path: "invoices", name: "sales-invoices", component: SalesInvoices, meta: { title: "Sales Invoices" } },
			{ path: "aging", name: "sales-aging", component: SalesAging, meta: { title: "AR Aging" } },
		],
	},
	{
		path: "/purchasing",
		component: PurchasingHome,
		meta: { title: "Purchasing" },
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
		meta: { title: "Inventory" },
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
		meta: { title: "Manufacturing" },
		children: [
			{ path: "", redirect: "/manufacturing/boms" },
			{ path: "boms", name: "manufacturing-boms", component: BOMs, meta: { title: "BOMs" } },
			{ path: "work-orders", name: "manufacturing-work-orders", component: WorkOrders, meta: { title: "Work Orders" } },
		],
	},
	{
		path: "/hr",
		component: HRHome,
		meta: { title: "People" },
		children: [
			{ path: "", redirect: "/hr/employees" },
			{ path: "employees", name: "hr-employees", component: Employees, meta: { title: "Employees" } },
			{ path: "attendance", name: "hr-attendance", component: HRAttendance, meta: { title: "Attendance" } },
			{ path: "leave", name: "hr-leave", component: LeaveApplications, meta: { title: "Leave" } },
			{ path: "payroll", name: "hr-payroll", component: Payroll, meta: { title: "Payroll" } },
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
			{ path: "compliance", name: "admin-compliance", component: AdminCompliance, meta: { title: "Compliance", requiresCompliance: true } },
		],
	},
	{ path: "/error", name: "server-error", component: ServerError, meta: { title: "Error" } },
	{ path: "/:pathMatch(.*)*", name: "not-found", component: NotFound, meta: { title: "Not found" } },
];

export const router = createRouter({
	history: createWebHashHistory(),
	routes,
});

router.afterEach((to) => {
	const base = "Stabler";
	document.title = to.meta?.title ? `${to.meta.title} · ${base}` : base;
});
