import { createRouter, createWebHashHistory } from "vue-router";
import { useSession } from "./stores/session.js";
import { t } from "./composables/i18n.js";
import Dashboard from "./pages/Dashboard.vue";
import GenesisWizard from "./pages/welcome/GenesisWizard.vue";
import ReportsHub from "./pages/ReportsHub.vue";
import ReportSalesByCustomer from "./pages/reports/SalesByCustomer.vue";
import ReportCustomerBalanceSummary from "./pages/reports/CustomerBalanceSummary.vue";
import ReportAgreementReceivables from "./pages/reports/AgreementReceivables.vue";
import ReportSalesByItem from "./pages/reports/SalesByItem.vue";
import ReportItemAbc from "./pages/reports/ItemAbc.vue";
import DrillReport from "./pages/reports/DrillReport.vue";
import ReportInventoryExpiry from "./pages/reports/InventoryExpiry.vue";
import ReportSalesTrend from "./pages/reports/ReportSalesTrend.vue";
import ReportStockMovementSummary from "./pages/reports/StockMovementSummary.vue";
import ReportStockDailyKpi from "./pages/reports/StockDailyKpi.vue";
import ReportStockLedgerDetail from "./pages/reports/StockLedgerDetail.vue";
import ReportPiProgress from "./pages/reports/PiProgress.vue";
import ReportPiGroupContainerStatus from "./pages/reports/PiGroupContainerStatus.vue";
import ReportSalesDetail from "./pages/reports/SalesDetail.vue";
import ReportPaymentsRegister from "./pages/reports/PaymentsRegister.vue";
import Profile from "./pages/Profile.vue";
import MoneyHome from "./pages/money/MoneyHome.vue";
import Accounts from "./pages/money/Accounts.vue";
import AccountLedger from "./pages/money/AccountLedger.vue";
import JournalEntries from "./pages/money/JournalEntries.vue";
import PaymentEntries from "./pages/money/PaymentEntries.vue";
import Expenses from "./pages/money/Expenses.vue";
import Transfers from "./pages/money/Transfers.vue";
import Reports from "./pages/money/Reports.vue";
import Approvals from "./pages/money/Approvals.vue";
import Reconcile from "./pages/money/Reconcile.vue";
import FxRevaluation from "./pages/money/FxRevaluation.vue";
import Budgets from "./pages/money/Budgets.vue";
import BudgetVsActual from "./pages/money/BudgetVsActual.vue";
import SalesHome from "./pages/sales/SalesHome.vue";
import Customers from "./pages/sales/Customers.vue";
import Quotations from "./pages/sales/Quotations.vue";
import SalesOrders from "./pages/sales/SalesOrders.vue";
import SalesOrderForm from "./pages/sales/SalesOrderForm.vue";
import SalesOrderBoard from "./pages/sales/SalesOrderBoard.vue";
import SourcingWorkspace from "./pages/tender/SourcingWorkspace.vue";
import PoControlBoard from "./pages/tender/PoControlBoard.vue";
import DeclarantQueue from "./pages/tender/DeclarantQueue.vue";
import LogistBoard from "./pages/tender/LogistBoard.vue";
import MyTenders from "./pages/tender/MyTenders.vue";
import DirectorBoard from "./pages/tender/DirectorBoard.vue";
import OperationsDesk from "./pages/tender/OperationsDesk.vue";
import TenderFlow from "./pages/tender/TenderFlow.vue";
import TenderCrmWrapper from "./pages/tender/TenderCrmWrapper.vue";
import TenderOverview from "./pages/tender/TenderOverview.vue";
import TenderDocuments from "./pages/tender/TenderDocuments.vue";
import SalesInvoices from "./pages/sales/SalesInvoices.vue";
import DeliveryNotes from "./pages/sales/DeliveryNotes.vue";
import SalesInvoiceForm from "./pages/sales/SalesInvoiceForm.vue";
import NewDirectInvoicePage from "./pages/sales/NewDirectInvoicePage.vue";
import SalesReturnForm from "./pages/sales/SalesReturnForm.vue";
import POS from "./pages/pos.vue";
import SalesAging from "./pages/sales/Aging.vue";
import ReservedStock from "./pages/sales/ReservedStock.vue";
import InvoicePrint from "./pages/sales/InvoicePrint.vue";
import Waybill from "./pages/sales/Waybill.vue";
import PurchaseInvoicePrint from "./pages/purchasing/InvoicePrint.vue";
import PurchasingHome from "./pages/purchasing/PurchasingHome.vue";
import Suppliers from "./pages/purchasing/Suppliers.vue";
import PurchaseInvoices from "./pages/purchasing/PurchaseInvoices.vue";
import PurchaseInvoiceForm from "./pages/purchasing/PurchaseInvoiceForm.vue";
import PurchaseOrders from "./pages/purchasing/PurchaseOrders.vue";
import PurchaseOrderForm from "./pages/purchasing/PurchaseOrderForm.vue";
import PaymentEntryForm from "./pages/money/PaymentEntryForm.vue";
import QuotationForm from "./pages/sales/QuotationForm.vue";
import PurchaseReceipts from "./pages/purchasing/PurchaseReceipts.vue";
import PurchasingAging from "./pages/purchasing/Aging.vue";
import InventoryHome from "./pages/inventory/InventoryHome.vue";
import Items from "./pages/inventory/Items.vue";
import ItemGroups from "./pages/inventory/ItemGroups.vue";
import PriceLists from "./pages/inventory/PriceLists.vue";
import Warehouses from "./pages/inventory/Warehouses.vue";
import StockStatus from "./pages/inventory/StockStatus.vue";
import StockLedger from "./pages/inventory/StockLedger.vue";
import StockEntries from "./pages/inventory/StockEntries.vue";
import LowStockAlerts from "./pages/inventory/LowStockAlerts.vue";
import MaterialStaging from "./pages/inventory/MaterialStaging.vue";
import StockReconciliation from "./pages/inventory/StockReconciliation.vue";
import ManufacturingHome from "./pages/manufacturing/ManufacturingHome.vue";
import BOMs from "./pages/manufacturing/BOMs.vue";
import WorkOrders from "./pages/manufacturing/WorkOrders.vue";
import ManufacturingOperatorBoard from "./pages/manufacturing/ManufacturingOperatorBoard.vue";
import HRHome from "./pages/hr/HRHome.vue";
import HROverview from "./pages/hr/Overview.vue";
import Employees from "./pages/hr/Employees.vue";
import EmployeeProfile from "./pages/hr/EmployeeProfile.vue";
import HRAttendance from "./pages/hr/Attendance.vue";
import LeaveApplications from "./pages/hr/LeaveApplications.vue";
import Payroll from "./pages/hr/Payroll.vue";
import RuleSets from "./pages/hr/RuleSets.vue";
import RuleSetEditor from "./pages/hr/RuleSetEditor.vue";
import AttendanceSimulator from "./pages/hr/AttendanceSimulator.vue";
import GateDevices from "./pages/hr/GateDevices.vue";
import EmployeeDeviceMapping from "./pages/hr/EmployeeDeviceMapping.vue";
import RawGateEvents from "./pages/hr/RawGateEvents.vue";
import ExceptionsQueue from "./pages/hr/ExceptionsQueue.vue";
import CorrectionsQueue from "./pages/hr/CorrectionsQueue.vue";
import PayrollReadiness from "./pages/hr/PayrollReadiness.vue";
import PayrollPreview from "./pages/hr/PayrollPreview.vue";
import EmployeeAdvances from "./pages/hr/EmployeeAdvances.vue";
import DataHealth from "./pages/hr/DataHealth.vue";
import TimepaySettings from "./pages/hr/TimepaySettings.vue";
import HrCalendar from "./pages/hr/HrCalendar.vue";
import SalaryPayments from "./pages/hr/SalaryPayments.vue";
import SFAHome from "./pages/sfa/SFAHome.vue";
import Outlets from "./pages/sfa/Outlets.vue";
import OutletGeo from "./pages/sfa/OutletGeo.vue";
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
import RemittanceHome from "./pages/remittance/RemittanceHome.vue";
import NewRemittance from "./pages/remittance/NewRemittance.vue";
import RemittanceTransfers from "./pages/remittance/RemittanceTransfers.vue";
import InstallmentHome from "./pages/installment/InstallmentHome.vue";
import NewContract from "./pages/installment/NewContract.vue";
import Contracts from "./pages/installment/Contracts.vue";
import InstallmentOverdue from "./pages/installment/Overdue.vue";
import InstallmentCalendar from "./pages/installment/InstallmentCalendar.vue";
import CrmHome from "./pages/crm/CrmHome.vue";
import CrmLeads from "./pages/crm/Leads.vue";
import CrmDeals from "./pages/crm/Deals.vue";
import Deal360View from "./pages/crm/Deal360View.vue";
import ManagerCockpit from "./pages/crm/ManagerCockpit.vue";
import CrmReport from "./pages/crm/CrmReport.vue";
import ServiceHome from "./pages/service/ServiceHome.vue";
import ServiceTickets from "./pages/service/Tickets.vue";
import ServiceBilling from "./pages/service/BillingQueue.vue";
import ServiceVisits from "./pages/service/Visits.vue";
import ServiceCalendar from "./pages/service/Calendar.vue";
import ServiceMap from "./pages/service/Map.vue";
import ServiceDashboard from "./pages/service/Dashboard.vue";
import ServiceEquipment from "./pages/service/Equipment.vue";
import BpmHome from "./pages/bpm/BpmHome.vue";
import BpmList from "./pages/bpm/BpmList.vue";
import ProcessEditor from "./pages/bpm/ProcessEditor.vue";
import AdminHome from "./pages/admin/AdminHome.vue";
import AdminUsers from "./pages/admin/Users.vue";
import AdminRoles from "./pages/admin/Roles.vue";
import AdminCompanies from "./pages/admin/Companies.vue";
import AdminCompliance from "./pages/admin/Compliance.vue";
import AdminAccessReview from "./pages/admin/AccessReview.vue";
import AdminPostingWindow from "./pages/admin/PostingWindow.vue";
import AdminRepostMonitor from "./pages/admin/RepostMonitor.vue";
import AdminKassaBot from "./pages/admin/KassaBot.vue";
import ImportsHome from "./pages/imports/ImportsHome.vue";
import ImportsDashboard from "./pages/imports/ImportsDashboard.vue";
import ImportOrders from "./pages/imports/ImportOrders.vue";
import ImportOrderForm from "./pages/imports/ImportOrderForm.vue";
import CommercialInvoices from "./pages/imports/CommercialInvoices.vue";
import CommercialInvoiceForm from "./pages/imports/CommercialInvoiceForm.vue";
import ProformaInvoices from "./pages/imports/ProformaInvoices.vue";
import PiCiDiscrepancies from "./pages/imports/PiCiDiscrepancies.vue";
import ProformaForm from "./pages/imports/ProformaForm.vue";
import PiAdvances from "./pages/imports/PiAdvances.vue";
import PiGroups from "./pages/imports/PiGroups.vue";
import VendorCategories from "./pages/inventory/VendorCategories.vue";
import ImportContainers from "./pages/imports/ImportContainers.vue";
import ImportTrucks from "./pages/imports/ImportTrucks.vue";
import GRNChecklists from "./pages/imports/GRNChecklists.vue";
import GRNChecklistDetail from "./pages/imports/GRNChecklistDetail.vue";
import TruckReceiptForm from "./pages/imports/TruckReceiptForm.vue";
import ImportContainerForm from "./pages/imports/ImportContainerForm.vue";
import ImportTruckForm from "./pages/imports/ImportTruckForm.vue";
import CustomsDeclarations from "./pages/imports/CustomsDeclarations.vue";
import CustomsDeclarationForm from "./pages/imports/CustomsDeclarationForm.vue";
import VetCertificates from "./pages/imports/VetCertificates.vue";
import ImportExpenses from "./pages/imports/ImportExpenses.vue";
import FreightBookings from "./pages/imports/FreightBookings.vue";
import LandedCostReview from "./pages/purchasing/LandedCostReview.vue";
import ContainerCostLedger from "./pages/imports/ContainerCostLedger.vue";
import LandedCostBills from "./pages/imports/LandedCostBills.vue";
import TransporterCenter from "./pages/imports/TransporterCenter.vue";
import NotFound from "./pages/NotFound.vue";
import ServerError from "./pages/ServerError.vue";
import Login from "./pages/Login.vue";

const routes = [
	{ path: "/", redirect: "/dashboard" },
	{ path: "/login", name: "login", component: Login, meta: { title: t("Sign in"), standalone: true, public: true, "public-after-login": true } },
	// Onboarding — reachable by any authenticated user while onboarding is not yet
	// complete (module: null = no module gating; the guard below confines
	// un-provisioned users here).
	{ path: "/welcome", name: "welcome", component: GenesisWizard, meta: { title: t("Welcome"), module: null, "public-after-login": true } },
	{ path: "/dashboard", name: "dashboard", component: Dashboard, meta: { title: t("Dashboard"), module: "dashboard" } },
	{
		path: "/imports",
		component: ImportsHome,
		meta: { title: t("Imports"), module: "imports" },
		children: [
			{ path: "", redirect: "/imports/dashboard" },
			{ path: "dashboard", name: "imports-dashboard", component: ImportsDashboard, meta: { title: t("Imports"), module: "imports" } },
			{ path: "orders", name: "imports-orders", component: ImportOrders, meta: { title: t("Import Orders"), module: "imports" } },
			{ path: "orders/new", name: "imports-order-new", component: ImportOrderForm, meta: { title: t("New Import Order"), module: "imports" } },
			{ path: "orders/:name", name: "imports-order", component: ImportOrderForm, meta: { title: t("Import Order"), module: "imports" } },
			{ path: "commercial-invoices", name: "imports-commercial-invoices", component: CommercialInvoices, meta: { title: t("Commercial Invoices"), module: "imports" } },
			{ path: "commercial-invoices/new", name: "imports-commercial-invoice-new", component: CommercialInvoiceForm, meta: { title: t("New Commercial Invoice"), module: "imports" } },
			{ path: "commercial-invoices/:name", name: "imports-commercial-invoice", component: CommercialInvoiceForm, meta: { title: t("Commercial Invoice"), module: "imports" } },
			{ path: "proformas", name: "imports-proformas", component: ProformaInvoices, meta: { title: t("Proforma Invoices"), module: "imports" } },
			{ path: "proformas/new", name: "imports-proforma-new", component: ProformaForm, meta: { title: t("New Proforma"), module: "imports" } },
			{ path: "discrepancies", name: "imports-discrepancies", component: PiCiDiscrepancies, meta: { title: t("PI ↔ CI deviations"), module: "imports" } },
			{ path: "proformas/:name(.*)", name: "imports-proforma", component: ProformaForm, meta: { title: t("Proforma Invoice"), module: "imports" } },
			{ path: "advances", name: "imports-advances", component: PiAdvances, meta: { title: t("PI Advances"), module: "imports" } },
			{ path: "pi-groups", name: "imports-pi-groups", component: PiGroups, meta: { title: t("PI Groups"), module: "imports" } },
			{ path: "containers", name: "imports-containers", component: ImportContainers, meta: { title: t("Containers"), module: "imports" } },
			{ path: "containers/new", name: "imports-container-new", component: ImportContainerForm, meta: { title: t("New Container"), module: "imports" } },
			{ path: "containers/:name", name: "imports-container", component: ImportContainerForm, meta: { title: t("Container"), module: "imports" } },
			{ path: "containers/:name/ledger", name: "imports-container-ledger", component: ContainerCostLedger, meta: { title: t("Container cost ledger"), module: "imports" } },
			{ path: "trucks", name: "imports-trucks", component: ImportTrucks, meta: { title: t("Trucks"), module: "imports" } },
			{ path: "trucks/new", name: "imports-truck-new", component: ImportTruckForm, meta: { title: t("New Truck"), module: "imports" } },
			{ path: "trucks/:name", name: "imports-truck", component: ImportTruckForm, meta: { title: t("Truck"), module: "imports" } },
			{ path: "grn-checklists", name: "imports-grn-checklists", component: GRNChecklists, meta: { title: t("GRN Checklists"), module: "imports" } },
			{ path: "grn-checklists/:name", name: "imports-grn-checklist", component: GRNChecklistDetail, meta: { title: t("GRN Checklist"), module: "imports" } },
			{ path: "truck-receipts/new", name: "imports-truck-receipt-new", component: TruckReceiptForm, meta: { title: t("Receive Truck"), module: "imports" } },
			{ path: "truck-receipts/:name", name: "imports-truck-receipt", component: TruckReceiptForm, meta: { title: t("Truck Receipt"), module: "imports" } },
			{ path: "customs", name: "imports-customs", component: CustomsDeclarations, meta: { title: t("Customs Declarations"), module: "imports" } },
			{ path: "customs/new", name: "imports-customs-new", component: CustomsDeclarationForm, meta: { title: t("New Customs Declaration"), module: "imports" } },
			{ path: "customs/:name", name: "imports-customs-declaration", component: CustomsDeclarationForm, meta: { title: t("Customs Declaration"), module: "imports" } },
			{ path: "vet-certificates", name: "imports-vet-certificates", component: VetCertificates, meta: { title: t("Veterinary Certificates"), module: "imports" } },
			{ path: "freight", name: "imports-freight", component: FreightBookings, meta: { title: t("Freight Bookings"), module: "imports" } },
			{ path: "expenses", name: "imports-expenses", component: ImportExpenses, meta: { title: t("Import Expenses"), module: "imports" } },
			{ path: "landed-cost/:grn", name: "imports-landed-cost", component: LandedCostReview, meta: { title: t("Landed Cost Review"), module: "imports" } },
			{ path: "bills", name: "imports-bills", component: LandedCostBills, meta: { title: t("Landed Cost Bills"), module: "imports" } },
			{ path: "transporters", name: "imports-transporters", component: TransporterCenter, meta: { title: t("Transport operations desk"), module: "imports" } },
		],
	},
	{ path: "/reports", name: "reports", component: ReportsHub, meta: { title: t("Reports") } },
	{ path: "/reports/sales-by-customer", name: "report-sales-by-customer", component: ReportSalesByCustomer, meta: { title: t("Sales by Customer"), module: "sales" } },
	{ path: "/reports/customer-balance-summary", name: "report-customer-balance-summary", component: ReportCustomerBalanceSummary, meta: { title: t("Customer Balance Summary"), module: "sales" } },
	{ path: "/reports/agreement-receivables", name: "report-agreement-receivables", component: ReportAgreementReceivables, meta: { title: t("Receivables by agreement"), module: "agreements" } },
	{ path: "/reports/sales-by-item", name: "report-sales-by-item", component: ReportSalesByItem, meta: { title: t("Sales by Item"), module: "sales" } },
	{ path: "/reports/item-abc", name: "report-item-abc", component: ReportItemAbc, meta: { title: t("Item ABC analysis"), module: "sales" } },
	{ path: "/reports/customer-abc", name: "report-customer-abc", component: DrillReport, meta: { title: "Customer ABC analysis", module: "sales", report: { title: "Customer ABC analysis", summaryApi: "stabler.api.reports.customer_abc", detailApi: "stabler.api.reports.sales_by_customer_detail", drillKey: "customer", detailParam: "customer", docPrefix: "/sales/invoices/", exportName: "customer_abc", filters: [ { key: "customers", label: t("Customers"), searchApi: "stabler.api.sales.list_customers", idKey: "name", display: (r) => r.customer_name || r.name, placeholder: t("All customers") }, { key: "items", label: t("Items"), searchApi: "stabler.api.inventory.list_items", idKey: "name", display: (r) => r.item_name || r.name, placeholder: t("All items") } ] } } },
	{ path: "/reports/purchases-by-supplier", name: "report-purchases-by-supplier", component: DrillReport, meta: { title: "Purchases by Supplier", module: "purchasing", report: { title: "Purchases by Supplier", summaryApi: "stabler.api.reports.purchases_by_supplier", detailApi: "stabler.api.reports.purchases_by_supplier_detail", drillKey: "supplier", detailParam: "supplier", docPrefix: "/purchasing/invoices/", exportName: "purchases_by_supplier", defaultSort: { sort_by: "total", sort_dir: "desc" }, filters: [ { key: "customers", label: t("Suppliers"), searchApi: "stabler.api.purchasing.list_suppliers", idKey: "name", display: (r) => r.supplier_name || r.name, placeholder: t("All suppliers") }, { key: "items", label: t("Items"), searchApi: "stabler.api.inventory.list_items", idKey: "name", display: (r) => r.item_name || r.name, placeholder: t("All items") } ] } } },
	{ path: "/reports/supplier-abc", name: "report-supplier-abc", component: DrillReport, meta: { title: "Supplier ABC analysis", module: "purchasing", report: { title: "Supplier ABC analysis", summaryApi: "stabler.api.reports.supplier_abc", detailApi: "stabler.api.reports.purchases_by_supplier_detail", drillKey: "supplier", detailParam: "supplier", docPrefix: "/purchasing/invoices/", exportName: "supplier_abc", filters: [ { key: "customers", label: t("Suppliers"), searchApi: "stabler.api.purchasing.list_suppliers", idKey: "name", display: (r) => r.supplier_name || r.name, placeholder: t("All suppliers") }, { key: "items", label: t("Items"), searchApi: "stabler.api.inventory.list_items", idKey: "name", display: (r) => r.item_name || r.name, placeholder: t("All items") } ] } } },
	{ path: "/reports/inventory-aging", name: "report-inventory-aging", component: DrillReport, meta: { title: "Inventory Aging", module: "inventory", report: { title: "Inventory Aging", summaryApi: "stabler.api.reports.inventory_aging", detailApi: "stabler.api.reports.sales_by_item_detail", drillKey: "item_code", detailParam: "item_code", docPrefix: "/sales/invoices/", exportName: "inventory_aging", defaultSort: { sort_by: "value", sort_dir: "desc" }, filters: [ { key: "items", label: t("Items"), searchApi: "stabler.api.inventory.list_items", idKey: "name", display: (r) => r.item_name || r.name, placeholder: t("All items") } ] } } },
	{ path: "/reports/inventory-expiry", name: "report-inventory-expiry", component: ReportInventoryExpiry, meta: { title: t("Batch Expiry"), module: "inventory" } },
	{ path: "/reports/margin-by-item", name: "report-margin-by-item", component: DrillReport, meta: { title: "Gross Margin by Item", module: "sales", report: { title: "Gross Margin by Item", summaryApi: "stabler.api.reports.gross_margin_by_item", detailApi: "stabler.api.reports.sales_by_item_detail", drillKey: "item_code", detailParam: "item_code", docPrefix: "/sales/invoices/", exportName: "margin_by_item", defaultSort: { sort_by: "margin", sort_dir: "desc" }, filters: [ { key: "customers", label: t("Customers"), searchApi: "stabler.api.sales.list_customers", idKey: "name", display: (r) => r.customer_name || r.name, placeholder: t("All customers") }, { key: "items", label: t("Items"), searchApi: "stabler.api.inventory.list_items", idKey: "name", display: (r) => r.item_name || r.name, placeholder: t("All items") } ] } } },
	{ path: "/reports/margin-by-customer", name: "report-margin-by-customer", component: DrillReport, meta: { title: "Gross Margin by Customer", module: "sales", report: { title: "Gross Margin by Customer", summaryApi: "stabler.api.reports.gross_margin_by_customer", detailApi: "stabler.api.reports.sales_by_customer_detail", drillKey: "customer", detailParam: "customer", docPrefix: "/sales/invoices/", exportName: "margin_by_customer", defaultSort: { sort_by: "margin", sort_dir: "desc" }, filters: [ { key: "customers", label: t("Customers"), searchApi: "stabler.api.sales.list_customers", idKey: "name", display: (r) => r.customer_name || r.name, placeholder: t("All customers") }, { key: "items", label: t("Items"), searchApi: "stabler.api.inventory.list_items", idKey: "name", display: (r) => r.item_name || r.name, placeholder: t("All items") } ] } } },
	{ path: "/reports/sales-by-salesperson", name: "report-sales-by-salesperson", component: DrillReport, meta: { title: "Sales by Salesperson", module: "sales", report: { title: "Sales by Salesperson", summaryApi: "stabler.api.reports.sales_by_salesperson", exportName: "sales_by_salesperson", defaultSort: { sort_by: "total", sort_dir: "desc" }, filters: [ { key: "customers", label: t("Customers"), searchApi: "stabler.api.sales.list_customers", idKey: "name", display: (r) => r.customer_name || r.name, placeholder: t("All customers") } ] } } },
	{ path: "/reports/sales-orders", name: "report-sales-orders", component: DrillReport, meta: { title: "Sales Orders (Booked)", module: "sales", report: { title: "Sales Orders (Booked)", summaryApi: "stabler.api.reports.sales_orders", exportName: "sales_orders", defaultSort: { sort_by: "booked", sort_dir: "desc" }, filters: [ { key: "customers", label: t("Customers"), searchApi: "stabler.api.sales.list_customers", idKey: "name", display: (r) => r.customer_name || r.name, placeholder: t("All customers") } ] } } },
	{ path: "/reports/sales-trend", name: "report-sales-trend", component: ReportSalesTrend, meta: { title: t("Sales Trend"), module: "sales" } },
	{ path: "/reports/stock-movement-summary", name: "report-stock-movement-summary", component: ReportStockMovementSummary, meta: { title: t("Stock movement summary"), module: "inventory" } },
	{ path: "/reports/stock-daily-kpi", name: "report-stock-daily-kpi", component: ReportStockDailyKpi, meta: { title: t("Daily in/out KPI"), module: "inventory" } },
	{ path: "/reports/stock-ledger-detail", name: "report-stock-ledger-detail", component: ReportStockLedgerDetail, meta: { title: t("Stock ledger detail"), module: "inventory" } },
	{ path: "/reports/pi-progress", name: "report-pi-progress", component: ReportPiProgress, meta: { title: t("PI Progress"), module: "imports" } },
	{ path: "/reports/pi-group-container-status", name: "report-pi-group-container-status", component: ReportPiGroupContainerStatus, meta: { title: t("PI Group Container Status"), module: "imports" } },
	{ path: "/reports/sales-detail", name: "report-sales-detail", component: ReportSalesDetail, meta: { title: t("Sales Detail"), module: "sales" } },
	{ path: "/reports/payments-register", name: "report-payments-register", component: ReportPaymentsRegister, meta: { title: t("Payments Register"), module: "money" } },
	{ path: "/profile", name: "profile", component: Profile, meta: { title: t("Profile") } },
	{ path: "/pos", name: "pos", component: POS, meta: { title: t("POS"), module: "sales" } },
	{ path: "/tender/desk", name: "tender-desk", component: OperationsDesk, meta: { title: t("Operations desk"), module: "tender" } },
	{ path: "/manufacturing/line", name: "manufacturing-line", component: ManufacturingOperatorBoard, meta: { title: t("Operator Kiosk") } },
	{ path: "/tender/overview", name: "tender-overview", component: TenderOverview, meta: { title: t("Where the pipeline stands"), module: "tender" } },
	{ path: "/tender/flow", name: "tender-flow", component: TenderFlow, meta: { title: t("Tender process flow"), module: "tender" } },
	{ path: "/tender/board", name: "tender-board", component: SalesOrderBoard, meta: { title: t("Contract board"), module: "tender" } },
	{ path: "/tender/crm", name: "tender-crm", component: TenderCrmWrapper, meta: { title: t("Tender CRM"), module: "tender" } },
	{ path: "/tender/documents", name: "tender-documents", component: TenderDocuments, meta: { title: t("Document center"), module: "tender" } },
	{ path: "/tender/sourcing", name: "tender-sourcing", component: SourcingWorkspace, meta: { title: t("Sourcing workspace"), module: "tender" } },
	{ path: "/tender/po-control", name: "tender-po-control", component: PoControlBoard, meta: { title: t("Tender PO control"), module: "tender" } },
	{ path: "/tender", redirect: "/tender/portfolio", meta: { module: "tender" } },
	{ path: "/tender/director", redirect: "/tender/portfolio", meta: { module: "tender" } },
	{ path: "/tender/portfolio", name: "tender-portfolio", component: DirectorBoard, meta: { title: t("Director board"), module: "tender" } },
	{ path: "/tender/my-tenders", name: "tender-my-tenders", component: MyTenders, meta: { title: t("My tenders"), module: "tender" } },
	{ path: "/tender/customs", name: "tender-customs", component: DeclarantQueue, meta: { title: t("Customs queue"), module: "tender" } },
	{ path: "/tender/logistics", name: "tender-logistics", component: LogistBoard, meta: { title: t("Logistics"), module: "tender" } },
	{
		path: "/money",
		component: MoneyHome,
		meta: { title: t("Money"), module: "money" },
		children: [
			{ path: "", redirect: "/money/accounts" },
			{ path: "accounts", name: "money-accounts", component: Accounts, meta: { title: t("Chart of Accounts") } },
			{ path: "accounts/:account/ledger", name: "money-account-ledger", component: AccountLedger, meta: { title: t("Account Ledger") } },
			{ path: "journals", name: "money-journals", component: JournalEntries, meta: { title: t("Journal Entries") } },
			{ path: "payments", name: "money-payments", component: PaymentEntries, meta: { title: t("Payments") } },
			{ path: "payments/new", name: "money-payment-new", component: PaymentEntryForm, meta: { title: t("New payment") } },
			{ path: "payments/:name", name: "money-payment", component: PaymentEntryForm, meta: { title: t("Payment Entry") } },
			{ path: "expenses", name: "money-expenses", component: Expenses, meta: { title: t("Expenses") } },
			{ path: "transfers", name: "money-transfers", component: Transfers, meta: { title: t("Transfers") } },
			{ path: "reports", name: "money-reports", component: Reports, meta: { title: t("Reports") } },
			{ path: "approvals", name: "money-approvals", component: Approvals, meta: { title: t("Approvals") } },
			{ path: "reconcile", name: "money-reconcile", component: Reconcile, meta: { title: t("Reconcile") } },
			{ path: "fx-revaluation", name: "money-fx-revaluation", component: FxRevaluation, meta: { title: t("FX Revaluation"), module: "fx_revaluation" } },
			{ path: "budgets", name: "money-budgets", component: Budgets, meta: { title: t("Budgets"), module: "budget" } },
			{ path: "budgets/vs-actual", name: "budget-vs-actual", component: BudgetVsActual, meta: { title: t("Budget vs Actual"), module: "budget" } },
		],
	},
	{
		path: "/sales",
		component: SalesHome,
		meta: { title: t("Sales"), module: "sales" },
		children: [
			{ path: "", redirect: "/sales/customers" },
			{ path: "customers", name: "sales-customers", component: Customers, meta: { title: t("Customers") } },
			{ path: "quotations", name: "sales-quotations", component: Quotations, meta: { title: t("Quotations") } },
			{ path: "quotations/new", name: "sales-quotation-new", component: QuotationForm, meta: { title: t("New Quotation") } },
			{ path: "quotations/:name", name: "sales-quotation", component: QuotationForm, meta: { title: t("Quotation") } },
			{ path: "orders", name: "sales-orders", component: SalesOrders, meta: { title: t("Sales Orders") } },
			{ path: "orders/new", name: "sales-order-new", component: SalesOrderForm, meta: { title: t("New Sales Order") } },
			{ path: "orders/:name", name: "sales-order", component: SalesOrderForm, meta: { title: t("Sales Order") } },
			{ path: "invoices", name: "sales-invoices", component: SalesInvoices, meta: { title: t("Sales Invoices") } },
			{ path: "delivery-notes", name: "sales-delivery-notes", component: DeliveryNotes, meta: { title: t("Delivery Notes") } },
			{ path: "invoices/new", name: "sales-invoice-new", component: NewDirectInvoicePage, meta: { title: t("New Direct Sales Invoice") } },
			{ path: "returns/new", name: "sales-return-new", component: SalesReturnForm, meta: { title: t("New Sales Return") } },
			{ path: "returns/:name", redirect: to => `/sales/invoices/${to.params.name}` },
			{ path: "pos", redirect: "/pos" },
			{ path: "reports", redirect: "/reports" },
			{ path: "invoices/:name/print", name: "sales-invoice-print", component: InvoicePrint, meta: { title: t("Invoice") } },
			{ path: "invoices/:name/waybill", name: "sales-invoice-waybill", component: Waybill, meta: { title: t("Yuk xati") } },
			{ path: "invoices/:name", name: "sales-invoice", component: SalesInvoiceForm, meta: { title: t("Sales Invoice") } },
			{ path: "aging", name: "sales-aging", component: SalesAging, meta: { title: t("AR Aging") } },
			{ path: "reserved-stock", name: "sales-reserved-stock", component: ReservedStock, meta: { title: t("Reserved Stock") } },
		],
	},
	{
		path: "/purchasing",
		component: PurchasingHome,
		meta: { title: t("Purchasing"), module: "purchasing" },
		children: [
			{ path: "", redirect: "/purchasing/suppliers" },
			{ path: "suppliers", name: "purchasing-suppliers", component: Suppliers, meta: { title: t("Suppliers") } },
			{ path: "orders", name: "purchasing-orders", component: PurchaseOrders, meta: { title: t("Purchase Orders") } },
			{ path: "orders/new", name: "purchasing-order-new", component: PurchaseOrderForm, meta: { title: t("New Purchase Order") } },
			{ path: "orders/:name", name: "purchasing-order", component: PurchaseOrderForm, meta: { title: t("Purchase Order") } },
			{ path: "receipts", name: "purchasing-receipts", component: PurchaseReceipts, meta: { title: t("Purchase Receipts") } },
			{ path: "invoices", name: "purchasing-invoices", component: PurchaseInvoices, meta: { title: t("Purchase Invoices") } },
			{ path: "invoices/new", name: "purchasing-invoice-new", component: PurchaseInvoiceForm, meta: { title: t("New Purchase Invoice") } },
			{ path: "invoices/:name/print", name: "purchasing-invoice-print", component: PurchaseInvoicePrint, meta: { title: t("Invoice") } },
			{ path: "invoices/:name", name: "purchasing-invoice", component: PurchaseInvoiceForm, meta: { title: t("Purchase Invoice") } },
			{ path: "aging", name: "purchasing-aging", component: PurchasingAging, meta: { title: t("AP Aging") } },
			{ path: "landed-cost-review/:document_type/:document_name", name: "purchasing-landed-cost-review", component: LandedCostReview, meta: { title: t("Landed Cost Review") } },
		],
	},
	{
		path: "/inventory",
		component: InventoryHome,
		meta: { title: t("Inventory"), module: "inventory" },
		children: [
			{ path: "", redirect: "/inventory/items" },
			{ path: "items", name: "inventory-items", component: Items, meta: { title: t("Items") } },
			{ path: "categories", name: "inventory-item-groups", component: ItemGroups, meta: { title: t("Categories") } },
			{ path: "prices", name: "inventory-prices", component: PriceLists, meta: { title: t("Price Lists") } },
			{ path: "warehouses", name: "inventory-warehouses", component: Warehouses, meta: { title: t("Warehouses") } },
			{ path: "stock-status", name: "inventory-stock-status", component: StockStatus, meta: { title: t("Stock Status") } },
			{ path: "staging", name: "inventory-staging", component: MaterialStaging, meta: { title: t("Material Staging") } },
			{ path: "entries", name: "inventory-entries", component: StockEntries, meta: { title: t("Stock Entries") } },
			{ path: "ledger", name: "inventory-ledger", component: StockLedger, meta: { title: t("Stock Ledger") } },
			{ path: "reconcile", name: "inventory-reconcile", component: StockReconciliation, meta: { title: t("Stock Reconciliation") } },
			{ path: "alerts", name: "inventory-alerts", component: LowStockAlerts, meta: { title: t("Low Stock Alerts") } },
			{ path: "vendor-categories", name: "inventory-vendor-categories", component: VendorCategories, meta: { title: t("Vendor Categories") } },
		],
	},
	{
		path: "/manufacturing",
		component: ManufacturingHome,
		meta: { title: t("Manufacturing"), module: "manufacturing" },
		children: [
			{ path: "", redirect: "/manufacturing/boms" },
			{ path: "boms", name: "manufacturing-boms", component: BOMs, meta: { title: t("BOMs") } },
			{ path: "work-orders", name: "manufacturing-work-orders", component: WorkOrders, meta: { title: t("Work Orders") } },
		],
	},
	{
		path: "/hr",
		component: HRHome,
		meta: { title: t("People"), module: "hr" },
		children: [
			{ path: "", redirect: "/hr/overview" },
			{ path: "overview", name: "hr-overview", component: HROverview, meta: { title: t("Overview") } },
			{ path: "employees", name: "hr-employees", component: Employees, meta: { title: t("Employees") } },
			{ path: "data-health", name: "hr-data-health", component: DataHealth, meta: { title: t("Data health") } },
			{ path: "employees/:name", name: "hr-employee-profile", component: EmployeeProfile, meta: { title: t("Employee Profile") } },
			{ path: "attendance", name: "hr-attendance", component: HRAttendance, meta: { title: t("Attendance") } },
			{ path: "leave", name: "hr-leave", component: LeaveApplications, meta: { title: t("Leave") } },
			{ path: "payroll", name: "hr-payroll", component: Payroll, meta: { title: t("Payroll") } },
			{ path: "attendance-rules", name: "hr-attendance-rules", component: RuleSets, meta: { title: t("Attendance Rule Sets") } },
			{ path: "attendance-rules/new", name: "hr-attendance-rule-new", component: RuleSetEditor, meta: { title: t("New Rule Set") } },
			{ path: "attendance-rules/:name", name: "hr-attendance-rule", component: RuleSetEditor, meta: { title: t("Rule Set") } },
			{ path: "attendance-simulator", name: "hr-attendance-simulator", component: AttendanceSimulator, meta: { title: t("Attendance Simulator") } },
			{ path: "gate-devices", name: "hr-gate-devices", component: GateDevices, meta: { title: t("Gate Devices") } },
			{ path: "employee-device-mapping", name: "hr-device-mapping", component: EmployeeDeviceMapping, meta: { title: t("Employee Device Mapping") } },
			{ path: "raw-gate-events", name: "hr-raw-events", component: RawGateEvents, meta: { title: t("Raw Gate Events") } },
			{ path: "timepay-settings", name: "hr-timepay-settings", component: TimepaySettings, meta: { title: t("TimePay Settings") } },
			{ path: "exceptions-queue", name: "hr-exceptions-queue", component: ExceptionsQueue, meta: { title: t("Exceptions Queue") } },
			{ path: "corrections", name: "hr-corrections", component: CorrectionsQueue, meta: { title: t("Corrections") } },
			{ path: "payroll-readiness", name: "hr-payroll-readiness", component: PayrollReadiness, meta: { title: t("Payroll Readiness") } },
			{ path: "payroll-preview", name: "hr-payroll-preview", component: PayrollPreview, meta: { title: t("Computed Pay") } },
			{ path: "advances", name: "hr-advances", component: EmployeeAdvances, meta: { title: t("Advances") } },
			{ path: "salary-payments", name: "hr-salary-payments", component: SalaryPayments, meta: { title: t("Salary payments") } },
			{ path: "calendar", name: "hr-calendar", component: HrCalendar, meta: { title: t("Holidays & periods") } },
		],
	},
	{
		path: "/sfa",
		component: SFAHome,
		meta: { title: t("Field Sales"), module: "field_sales" },
		children: [
			{ path: "", redirect: "/sfa/outlets" },
			{ path: "outlets", name: "sfa-outlets", component: Outlets, meta: { title: t("Outlets") } },
			{ path: "locations", name: "sfa-locations", component: OutletGeo, meta: { title: t("Outlet Locations") } },
			{ path: "routes", name: "sfa-routes", component: Routes, meta: { title: t("Routes") } },
			{ path: "visits", name: "sfa-visits", component: Visits, meta: { title: t("Visits") } },
			{ path: "field-users", name: "sfa-field-users", component: FieldUsers, meta: { title: t("Field Users") } },
			{ path: "van-stock", name: "sfa-van-stock", component: VanStock, meta: { title: t("Van Stock") } },
			{ path: "promos", name: "sfa-promos", component: Promos, meta: { title: t("Promos") } },
			{ path: "photos", name: "sfa-photos", component: Photos, meta: { title: t("Photos") } },
			{ path: "planograms", name: "sfa-planograms", component: Planograms, meta: { title: t("Planograms") } },
			{ path: "osa", name: "sfa-osa", component: OSA, meta: { title: t("OSA Audits") } },
			{ path: "receivables", name: "sfa-receivables", component: Receivables, meta: { title: t("Receivables") } },
		],
	},
	{
		path: "/marketing",
		component: MarketingHome,
		meta: { title: t("Trade Marketing"), module: "marketing" },
		children: [
			{ path: "", redirect: "/marketing/plans" },
			{ path: "plans", name: "marketing-plans", component: PromoPlans, meta: { title: t("Promo Plans") } },
			{ path: "roi", name: "marketing-roi", component: ROI, meta: { title: t("Campaign ROI") } },
			{ path: "claims", name: "marketing-claims", component: Claims, meta: { title: t("Claims") } },
			{ path: "equipment", name: "marketing-equipment", component: Equipment, meta: { title: t("Equipment") } },
			{ path: "repairs", name: "marketing-repairs", component: RepairRequests, meta: { title: t("Repair Requests") } },
		],
	},
	{
		path: "/remittance",
		component: RemittanceHome,
		meta: { title: t("Remittance"), module: "remittance" },
		children: [
			{ path: "", redirect: "/remittance/new" },
			{ path: "new", name: "remittance-new", component: NewRemittance, meta: { title: t("New Transfer") } },
			{ path: "transfers", name: "remittance-transfers", component: RemittanceTransfers, meta: { title: t("Transfers") } },
		],
	},
	{
		path: "/installment",
		component: InstallmentHome,
		meta: { title: t("Installment"), module: "installment" },
		children: [
			{ path: "", redirect: "/installment/new" },
			{ path: "new", name: "installment-new", component: NewContract, meta: { title: t("New Contract") } },
			{ path: "contracts", name: "installment-contracts", component: Contracts, meta: { title: t("Contracts") } },
			{ path: "overdue", name: "installment-overdue", component: InstallmentOverdue, meta: { title: t("Overdue") } },
			{ path: "calendar", name: "installment-calendar", component: InstallmentCalendar, meta: { title: t("Calendar") } },
		],
	},
	{
		path: "/crm",
		component: CrmHome,
		meta: { title: t("CRM"), module: "crm" },
		children: [
			{ path: "", redirect: "/crm/leads" },
			{ path: "leads", name: "crm-leads", component: CrmLeads, meta: { title: t("Leads") } },
			{ path: "deals", name: "crm-deals", component: CrmDeals, meta: { title: t("Deals") } },
			{ path: "deals/:name", name: "crm-deal-360", component: Deal360View, meta: { title: t("Deal 360") } },
			{ path: "cockpit", name: "crm-cockpit", component: ManagerCockpit, meta: { title: t("Manager Cockpit") } },
			{ path: "report", name: "crm-report", component: CrmReport, meta: { title: t("CRM Report") } },
		],
	},
	{
		path: "/service",
		component: ServiceHome,
		meta: { title: t("Service"), module: "service" },
		children: [
			{ path: "", redirect: "/service/tickets" },
			{ path: "dashboard", name: "service-dashboard", component: ServiceDashboard, meta: { title: t("Service Dashboard") } },
			{ path: "tickets", name: "service-tickets", component: ServiceTickets, meta: { title: t("Service Tickets") } },
			{ path: "visits", name: "service-visits", component: ServiceVisits, meta: { title: t("Service Visits") } },
			{ path: "billing", name: "service-billing", component: ServiceBilling, meta: { title: t("Service Billing") } },
			{ path: "calendar", name: "service-calendar", component: ServiceCalendar, meta: { title: t("Service Calendar") } },
			{ path: "equipment", name: "service-equipment", component: ServiceEquipment, meta: { title: t("Service Equipment") } },
			{ path: "map", name: "service-map", component: ServiceMap, meta: { title: t("Service Map") } },
		],
	},
	{
		path: "/bpm",
		component: BpmHome,
		meta: { title: t("Processes"), module: "bpm" },
		children: [
			{ path: "", name: "bpm-list", component: BpmList, meta: { title: t("Processes") } },
			{ path: ":name", name: "bpm-editor", component: ProcessEditor, meta: { title: t("Process") } },
		],
	},
	{
		path: "/admin",
		component: AdminHome,
		meta: { title: t("Admin"), module: "admin", requiresAdmin: true },
		children: [
			{ path: "", redirect: "/admin/users" },
			{ path: "users", name: "admin-users", component: AdminUsers, meta: { title: t("Users") } },
			{ path: "roles", name: "admin-roles", component: AdminRoles, meta: { title: t("Roles") } },
			{ path: "access-review", name: "admin-access", component: AdminAccessReview, meta: { title: t("Access Review") } },
			{ path: "companies", name: "admin-companies", component: AdminCompanies, meta: { title: t("Companies") } },
			{ path: "compliance", name: "admin-compliance", component: AdminCompliance, meta: { title: t("Compliance") } },
			{ path: "posting-window", name: "admin-posting-window", component: AdminPostingWindow, meta: { title: t("Posting Window") } },
			{ path: "repost-queue", name: "admin-repost-queue", component: AdminRepostMonitor, meta: { title: t("Repost queue") } },
			{ path: "kassa-bot", name: "admin-kassa-bot", component: AdminKassaBot, meta: { title: t("Kassa Bot") } },
		],
	},
	{ path: "/error", name: "server-error", component: ServerError, meta: { title: t("Error") } },
	{ path: "/:pathMatch(.*)*", name: "not-found", component: NotFound, meta: { title: t("Not found") } },
];

export const router = createRouter({
	history: createWebHashHistory(),
	routes,
});

// Ordered list of modules → paths used to pick the first accessible landing page.
// A Sales-only user lands at /sales; an admin (or user with dashboard access) lands at /dashboard.
const LANDING_ORDER = [
	{ key: "dashboard", path: "/dashboard" },
	{ key: "money", path: "/money" },
	{ key: "sales", path: "/sales" },
	{ key: "purchasing", path: "/purchasing" },
	{ key: "imports", path: "/imports" },
	{ key: "inventory", path: "/inventory" },
	{ key: "manufacturing", path: "/manufacturing" },
	{ key: "hr", path: "/hr" },
	{ key: "field_sales", path: "/sfa" },
	{ key: "marketing", path: "/marketing" },
	{ key: "crm", path: "/crm" },
	{ key: "service", path: "/service" },
	{ key: "bpm", path: "/bpm" },
	{ key: "remittance", path: "/remittance" },
	{ key: "installment", path: "/installment" },
	{ key: "compliance", path: "/admin/compliance" },
];

function landingPath(session) {
	for (const { key, path } of LANDING_ORDER) {
		if (session.canAccessModule(key)) return path;
	}
	return "/error";
}

// WP-271 — local "onboarding completed" flag, set by the Genesis wizard on a
// successful provision so the guard lets the user through immediately (before the
// next boot refresh). Read defensively (private mode can block storage).
function localOnboardingFlag() {
	try {
		return localStorage.getItem("stabler.onboarding.completed") === "1";
	} catch (_) {
		return false;
	}
}

router.beforeEach(async (to) => {
	const session = useSession();

	if (to.path === "/login" || to.matched.some((r) => r.meta?.public)) {
		if (session.user?.id && session.user.id !== "Guest") {
			return landingPath(session);
		}
		return;
	}

	// Await boot so the access decision uses real allowedModules on the very first navigation.
	// ensureBoot() is idempotent and deduplicates concurrent calls.
	await session.ensureBoot();

	if (session.user?.id === "Guest" || !session.user?.id) {
		if (to.path !== "/manufacturing/line" && to.path !== "/login") {
			return { path: "/login", query: { "redirect-to": to.fullPath } };
		}
	}

	// WP-271 — force onboarding for authenticated users. A user who has NOT yet
	// provisioned a company is confined to the Genesis wizard: direct-URL access to
	// /sales, /money, … is redirected to /welcome until onboarding completes.
	// "Completed" = the local flag set by the wizard OR the user already owns a
	// company. Routes flagged `public-after-login` (i.e. /welcome) stay reachable.
	if (session.user?.id && session.user.id !== "Guest") {
		const onboardingDone =
			localOnboardingFlag() || (Array.isArray(session.companies) && session.companies.length > 0);
		const isPublicAfterLogin = to.matched.some((r) => r.meta && r.meta["public-after-login"]);
		if (!onboardingDone) {
			if (!isPublicAfterLogin) return "/welcome";
		} else if (isPublicAfterLogin && to.path !== landingPath(session)) {
			// A provisioned user shouldn't re-enter the wizard — send them home.
			return landingPath(session);
		}
	}

	/* Tender şirketinde pano = direktör portföyü.
	 *
	 * `/dashboard`'daki finans panosu tender'da zaten hiç çizilmiyordu (Dashboard.vue
	 * onun dört isteğini atlıyordu), yerine hattın genel görünümü duruyordu. İki ekran
	 * aynı soruya iki yerden cevap veriyordu; portföy artık TEK giriş. Genel bakış
	 * (huni + süreç şeridi) kendi rotasına taşındı: `/tender/overview`.
	 *
	 * Muhafızda, `redirect:` ile değil: karar KULLANICIYA bağlı — tender'ı olmayan
	 * şirket finans panosunu, ithalat şirketi kontrol merkezini görmeye devam ediyor.
	 * Statik bir redirect ikisini de yok ederdi. */
	if (to.path === "/dashboard" && session.canAccessModule("tender")) {
		return "/tender/portfolio";
	}

	if (to.matched.some((r) => r.meta.requiresAdmin) && !session.isAdmin) {
		const dest = landingPath(session);
		if (to.path === dest) return;
		return dest;
	}
	if (to.path === "/reports" || to.path.startsWith("/reports/")) {
		const canSeeReports = session.isAdmin ||
			session.canAccessModule("sales") ||
			session.canAccessModule("purchasing") ||
			session.canAccessModule("hr") ||
			session.canAccessModule("money") ||
			session.canAccessModule("inventory");
		if (!canSeeReports) {
			const dest = landingPath(session);
			if (to.path === dest) return;
			return dest;
		}
	}
	const moduleRoute = to.matched.find((r) => r.meta.module);
	if (moduleRoute && !session.canAccessModule(moduleRoute.meta.module)) {
		const tenderDrilldownRoutes = new Set([
			"sales-orders",
			"sales-invoices",
			"sales-delivery-notes",
			"purchasing-orders",
			"purchasing-receipts",
			"purchasing-invoices",
		]);
		const isTenderDrilldown =
			to.query.tender_only === "1" &&
			tenderDrilldownRoutes.has(String(to.name || "")) &&
			session.canAccessModule("tender");
		if (isTenderDrilldown) {
			// Dashboard drill-downs stay available to tender-only roles.
		} else if (to.path === "/inventory/stock-status" && session.canAccessModule("manufacturing")) {
			// Allow line operators to view their assigned stock status page
		} else {
			const dest = landingPath(session);
			if (to.path === dest) return;
			return dest;
		}
	}
});

router.afterEach((to) => {
	const base = "Stabler";
	document.title = to.meta?.title ? `${to.meta.title} · ${base}` : base;
});
