<script setup>
/**
 * Müşteri Merkezi — paylaşılan `PartyCenter` kabuğunun ince sarmalayıcısı.
 *
 * Liste, kokpit, ekstre, sekmeler ve 2 panelli yerleşim `components/party/`
 * altında yaşar; burada yalnızca SATIŞA ÖZGÜ olanlar kalır:
 *   · `stabler.api.sales.*` uç noktaları ve alan adları (`api` prop'u)
 *   · başlık eylemleri (Düzenle / Yeniden dağıt / Ödeme / Ekstre / Yeni)
 *   · müşteri oluştur-düzenle formunun alanları
 *   · ödeme + üst kayıt diyalogları
 *
 * Üst kayıt kuralı (bilerek): İşlemler alt lokasyonlarda kaydedilir, bu yüzden
 * üst kayıtta Yeni Fatura / Yeni SO pasiftir — ama Ödeme AKTİF kalır, çünkü üst
 * kaydın ödemesi toplu bölüştürme diyaloğunu açar.
 */
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import Select from "../../components/Select.vue";
import PartyPaymentModal from "../../components/PartyPaymentModal.vue";
import ParentBulkPaymentDialog from "../../components/ParentBulkPaymentDialog.vue";
import ParentReallocateDialog from "../../components/ParentReallocateDialog.vue";
import NewDirectInvoiceModal from "../../components/NewDirectInvoiceModal.vue";
import PartyCenter from "../../components/party/PartyCenter.vue";

const session = useSession();
const router = useRouter();
const { activeCompany, user } = storeToRefs(session);
// Direct (order-less) sales invoices are an imports-module capability.
const directInvoiceEnabled = computed(() => session.canAccessModule("imports"));

const { confirm } = useConfirm();
const toast = useToast();

const CUSTOMER_TYPES = ["Company", "Individual", "Partnership"];

const pc = ref(null);
const selected = ref(null);
const selectedDetail = ref(null);

const partyPayOpen = ref(false);
const bulkPayOpen = ref(false);
const reallocateOpen = ref(false);
const directInvoiceOpen = ref(false);

const selectedIsParent = computed(() => !!selectedDetail.value?.is_parent);
// Legacy parent-PE reallocation is a finance-only tool (also enforced server-side).
const canReallocate = computed(
	() =>
		selectedIsParent.value &&
		(session.isAdmin || (session.roles || []).includes("Accounts Manager"))
);

const centerApi = {
	list: "stabler.api.sales.list_customers_with_balances",
	detail: "stabler.api.sales.customer_detail",
	ledger: "stabler.api.sales.customer_ledger",
	orders: "stabler.api.sales.list_sales_orders",
	quotes: "stabler.api.sales.list_quotations",
	childrenBalanceMap: "stabler.api.sales.customer_children_balance_map",
	param: "customer",
	nameField: "customer_name",
	groupField: "customer_group",
	territoryField: "territory",
	parentField: "parent_customer",
	invoiceDoctype: "Sales Invoice",
	orderDoctype: "Sales Order",
	quotationDoctype: "Quotation",
	ledgerReportKey: "customer_ledger",
};

const centerRoutes = {
	back: "/sales",
	vouchers: {
		"Payment Entry": "/money/payments/:name",
		"Sales Invoice": "/sales/invoices/:name",
		"Sales Order": "/sales/orders/:name",
		Quotation: "/sales/quotations/:name",
		"Journal Entry": { path: "/money/journals", query: "open" },
	},
};

const centerCockpit = computed(() => ({
	method: "stabler.api.sales.receivables_cockpit",
	keys: {
		total: "total_receivable",
		today: "payments_received_today",
		trend: "trend_8_weeks",
		top: "top_debtors",
	},
	labels: {
		total: t("Total receivable"),
		today: t("Payments received today"),
		trend: t("Receivables trend (8 weeks)"),
		trendSeries: t("Receivables"),
		top: t("Top debtors"),
		empty: t("No outstanding balances."),
	},
}));

const centerLabels = computed(() => ({
	searchPlaceholder: t("Search customers… ⌘K"),
	groupLabel: t("Customer group"),
	allGroups: t("All groups"),
	allTerritories: t("All territories"),
	emptyTitle: t("No customers"),
	emptySubtitle: t("Create your first customer to start invoicing."),
	emptyAction: t("New customer"),
	grandTotalLabel: t("All records"),
	allRecords: t("All records"),
	parentLabel: t("Parent"),
	childrenTab: t("Locations"),
	includeChildren: t("Include child transactions"),
	lifetimeLabel: t("Lifetime sales"),
	noOrdersTitle: t("No orders yet"),
	loadError: t("Failed to load customers."),
}));

const headerBalance = computed(() => {
	if (selectedIsParent.value) return selectedDetail.value?.cumulative_balance_acc ?? 0;
	return selected.value?.balance_acc ?? selected.value?.balance_base ?? 0;
});
const headerBalanceCurrency = computed(
	() => selected.value?.account_currency || selectedDetail.value?.account_currency || session.currency
);

// Naming the party and the amount keeps the click unambiguous. Parents keep the
// bulk-split flow, so the wording differs there on purpose.
const paymentButtonTitle = computed(() => {
	if (!selected.value) return "";
	const who = selected.value.customer_name || selected.value.name;
	const amount = formatMoney(headerBalance.value, headerBalanceCurrency.value, user.value.language);
	if (selectedIsParent.value) return `${t("Split one payment across child locations")} — ${who}`;
	return `${t("Payment")} — ${who} (${selected.value.name}) · ${amount}`;
});

function onSelect(row) {
	selected.value = row;
	if (!row) selectedDetail.value = null;
}
function onDetail(detail) {
	selectedDetail.value = detail;
}

// Para hareketinden sonra hem liste bakiyeleri hem açık kaydın ekstresi/
// siparişleri tazelenir (refreshSelected → ekstre + siparişler + detay).
function refreshAfterMoney() {
	pc.value?.reload();
	pc.value?.refreshSelected();
}

// ─────────────────────────── Create / edit form ───────────────────────────
const createOpen = ref(false);
const editMode = ref(false);
const editingName = ref("");
const submitting = ref(false);
const deleting = ref(false);
const submitError = ref("");
const groupOptions = ref([]);
const territoryOptions = ref([]);
const priceListOptions = ref([]);
const currencyOptions = ref([]);
const optionsLoaded = ref(false);

function blankCustomer() {
	return {
		customer_name: "",
		customer_type: "Company",
		customer_group: "",
		territory: "",
		email_id: "",
		mobile_no: "",
		tax_id: "",
		default_price_list: "",
		default_currency: "",
		parent_customer: "",
		job_status: "",
	};
}
const form = ref(blankCustomer());

const customerTypeOptions = computed(() => CUSTOMER_TYPES.map((ct) => ({ value: ct, label: t(ct) })));

// Parent picker (New/Edit): only standalone/parent customers (no own parent),
// excluding the customer being edited. Job status shown only when a parent is set.
const parentPickerOptions = computed(() => {
	const self = editingName.value;
	return (pc.value?.rows || [])
		.filter((c) => !c.parent_customer && c.name !== self)
		.map((c) => ({ name: c.name, label: c.customer_name || c.name }));
});
const jobStatusOptions = computed(() => [
	{ value: "", label: t("— none —") },
	{ value: "Active", label: t("Active") },
	{ value: "Completed", label: t("Completed") },
	{ value: "On Hold", label: t("On Hold") },
	{ value: "Cancelled", label: t("Cancelled") },
]);

async function loadCreateOptions() {
	if (optionsLoaded.value) return;
	try {
		const [groups, terrs, priceLists, currencies] = await Promise.all([
			call("stabler.api.sales.list_customer_groups", { limit: 200 }),
			call("stabler.api.sales.list_territories", { limit: 200 }),
			call("stabler.api.sales.list_price_lists", { selling_only: 1, limit: 200 }),
			call("stabler.api.sales.list_currencies", {}),
		]);
		groupOptions.value = groups || [];
		territoryOptions.value = terrs || [];
		priceListOptions.value = priceLists || [];
		currencyOptions.value = currencies || [];
		optionsLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || t("Failed to load options.");
	}
}

function openCreate() {
	form.value = blankCustomer();
	submitError.value = "";
	editMode.value = false;
	editingName.value = "";
	createOpen.value = true;
	loadCreateOptions();
}

async function openEdit(c) {
	if (!c) return;
	submitError.value = "";
	editMode.value = true;
	editingName.value = c.name;
	createOpen.value = true;
	loadCreateOptions();
	try {
		const data = await call("stabler.api.sales.get_customer", { name: c.name });
		form.value = {
			customer_name: data.customer_name || "",
			customer_type: data.customer_type || "Company",
			customer_group: data.customer_group || "",
			territory: data.territory || "",
			email_id: data.email_id || "",
			mobile_no: data.mobile_no || "",
			tax_id: data.tax_id || "",
			default_price_list: data.default_price_list || "",
			default_currency: data.default_currency || "",
			parent_customer: data.parent_customer || "",
			job_status: data.job_status || "",
		};
	} catch (err) {
		submitError.value = err?.message || t("Failed to load customer.");
	}
}

function closeCreate() {
	if (submitting.value || deleting.value) return;
	createOpen.value = false;
}

async function submitCreate() {
	submitError.value = "";
	const f = form.value;
	if (!f.customer_name.trim()) return (submitError.value = t("Customer name is required."));
	// Job status only applies to a child (parent set); clear it otherwise.
	const jobStatus = f.parent_customer ? f.job_status || "" : "";
	const payload = {
		customer_name: f.customer_name.trim(),
		customer_type: f.customer_type,
		customer_group: f.customer_group || null,
		territory: f.territory || null,
		email_id: f.email_id || null,
		mobile_no: f.mobile_no || null,
		tax_id: f.tax_id || null,
		default_price_list: f.default_price_list || null,
		default_currency: f.default_currency || null,
		parent_customer: f.parent_customer || "",
		job_status: jobStatus,
	};
	submitting.value = true;
	try {
		if (editMode.value) {
			await call("stabler.api.sales.update_customer", { name: editingName.value, ...payload });
		} else {
			await call("stabler.api.sales.create_customer", payload);
		}
		createOpen.value = false;
		// reload() re-resolves the open record from the fresh rows, so an edit to
		// the selected customer updates the right pane too.
		await pc.value?.reload();
	} catch (err) {
		submitError.value = err?.message || t("Failed to save customer.");
	} finally {
		submitting.value = false;
	}
}

async function deleteCustomer() {
	if (!editMode.value || !editingName.value) return;
	const ok = await confirm({
		title: t("Delete Customer"),
		body: t("Delete customer") + " " + editingName.value + "? " + t("This cannot be undone."),
		confirmLabel: t("Delete"),
		cancelLabel: t("Cancel"),
		danger: true,
	});
	if (!ok) return;
	deleting.value = true;
	submitError.value = "";
	try {
		await call("stabler.api.sales.delete_customer", { name: editingName.value });
		toast.success(t("Customer deleted."));
		createOpen.value = false;
		await pc.value?.reload();
	} catch (err) {
		submitError.value = err?.message || t("Failed to delete customer.");
	} finally {
		deleting.value = false;
	}
}
</script>

<template>
	<PartyCenter
		ref="pc"
		party-type="Customer"
		:api="centerApi"
		:labels="centerLabels"
		:hierarchy="true"
		:cockpit="centerCockpit"
		state-key="stabler.customers.listState"
		:routes="centerRoutes"
		:form-open="createOpen"
		:form-mode="editMode ? 'edit' : 'create'"
		:form-title="editMode ? t('Edit customer') : t('New customer')"
		:submitting="submitting"
		:deleting="deleting"
		:submit-error="submitError"
		:can-submit="!!form.customer_name.trim()"
		:can-delete="editMode"
		@create="openCreate"
		@select="onSelect"
		@detail="onDetail"
		@close-form="closeCreate"
		@submit-form="submitCreate"
		@delete-form="deleteCustomer"
	>
		<template #actions="{ selected: sel, isParent, balance, balanceCurrency, exportLedger }">
			<button type="button" class="ds-btn" @click="openEdit(sel)">
				<i class="ti ti-pencil"></i>{{ t("Edit") }}
			</button>
			<button
				v-if="canReallocate"
				type="button"
				class="ds-btn"
				:title="t('Reallocate a legacy advance to child locations')"
				@click="reallocateOpen = true"
			>
				<i class="ti ti-arrows-shuffle"></i>{{ t("Reallocate") }}
			</button>
			<!-- Paying the wrong customer is the expensive mistake on this screen,
			     so the button echoes the target in the tooltip and the amount
			     inline. Parent keeps the bulk-split dialog — deliberately still
			     enabled while New Invoice / New SO are not. -->
			<button
				type="button"
				class="ds-btn"
				:title="paymentButtonTitle"
				@click="isParent ? (bulkPayOpen = true) : (partyPayOpen = true)"
			>
				<i class="ti ti-cash"></i>{{ t("Payment") }}
				<span class="font-monospace ms-1">
					{{ formatMoney(balance, balanceCurrency, user.language) }}
				</span>
			</button>
			<button
				type="button"
				class="ds-btn"
				:title="t('Professional Excel export of this ledger')"
				@click="exportLedger"
			>
				<i class="ti ti-file-spreadsheet"></i>{{ t("Statement") }}
			</button>
			<button
				v-if="directInvoiceEnabled"
				type="button"
				class="ds-btn ds-btn--primary"
				:disabled="isParent"
				:title="isParent ? t('Transactions are recorded on child locations') : ''"
				@click="router.push({ path: '/sales/invoices/new', query: { new_for: sel.name } })"
			>
				<i class="ti ti-file-plus"></i>{{ t("New Invoice") }}
			</button>
			<router-link
				v-else
				:to="{ path: '/sales/orders/new', query: { new_for: sel.name } }"
				class="ds-btn ds-btn--primary"
				:class="{ disabled: isParent }"
				:title="isParent ? t('Transactions are recorded on child locations') : ''"
			>
				<i class="ti ti-file-plus"></i>{{ t("New SO") }}
			</router-link>
		</template>

		<template #form-fields>
			<div class="row g-3">
				<div class="col-12">
					<label class="form-label">{{ t("Customer name") }} <span class="text-danger">*</span></label>
					<input v-model="form.customer_name" type="text" class="form-control" autofocus />
				</div>
				<div class="col-md-6">
					<label class="form-label">{{ t("Type") }}</label>
					<Select v-model="form.customer_type" :options="customerTypeOptions" />
				</div>
				<div class="col-md-6">
					<label class="form-label">{{ t("Tax ID") }}</label>
					<input v-model="form.tax_id" type="text" class="form-control" />
				</div>
				<div class="col-md-6">
					<label class="form-label">{{ t("Customer group") }}</label>
					<Select
						v-model="form.customer_group"
						:options="groupOptions"
						value-key="name"
						label-key="name"
						:placeholder="t('— default —')"
					/>
				</div>
				<div class="col-md-6">
					<label class="form-label">{{ t("Territory") }}</label>
					<Select
						v-model="form.territory"
						:options="territoryOptions"
						value-key="name"
						label-key="name"
						:placeholder="t('— default —')"
					/>
				</div>
				<div class="col-md-6">
					<label class="form-label">{{ t("Email") }}</label>
					<input v-model="form.email_id" type="email" class="form-control" />
				</div>
				<div class="col-md-6">
					<label class="form-label">{{ t("Mobile") }}</label>
					<input v-model="form.mobile_no" type="tel" class="form-control" />
				</div>
				<div class="col-md-6">
					<label class="form-label">{{ t("Default price list") }}</label>
					<Select
						v-model="form.default_price_list"
						:options="priceListOptions"
						value-key="name"
						:placeholder="t('— global default —')"
					>
						<template #option="{ option: p }">
							{{ p.name }}<span v-if="p.currency"> ({{ p.currency }})</span>
						</template>
						<template #selected="{ option: p }">
							{{ p.name }}<span v-if="p.currency"> ({{ p.currency }})</span>
						</template>
					</Select>
				</div>
				<div class="col-md-6">
					<label class="form-label">{{ t("Default currency") }}</label>
					<Select
						v-model="form.default_currency"
						class="font-monospace"
						:options="currencyOptions"
						value-key="name"
						:placeholder="t('— company default —')"
					>
						<template #option="{ option: c }">
							{{ c.name }}<template v-if="c.symbol"> ({{ c.symbol }})</template>
						</template>
						<template #selected="{ option: c }">
							{{ c.name }}<template v-if="c.symbol"> ({{ c.symbol }})</template>
						</template>
					</Select>
				</div>
				<div class="col-md-6">
					<label class="form-label">{{ t("Parent Customer") }}</label>
					<Select
						v-model="form.parent_customer"
						:options="parentPickerOptions"
						value-key="name"
						label-key="label"
						:placeholder="t('— none —')"
					/>
				</div>
				<div v-if="form.parent_customer" class="col-md-6">
					<label class="form-label">{{ t("Job Status") }}</label>
					<Select v-model="form.job_status" :options="jobStatusOptions" />
				</div>
			</div>
		</template>
	</PartyCenter>

	<!-- Payment Entry Modal -->
	<PartyPaymentModal
		v-if="selected"
		:open="partyPayOpen"
		party-type="Customer"
		:party="selected.name"
		:party-name="selected.customer_name"
		:company="activeCompany"
		@close="partyPayOpen = false"
		@paid="
			partyPayOpen = false;
			refreshAfterMoney();
		"
	/>

	<!-- Parent bulk payment — split one payment across child locations -->
	<ParentBulkPaymentDialog
		v-if="selected && selectedIsParent"
		:open="bulkPayOpen"
		:company="activeCompany"
		:parent="selected.name"
		:parent-name="selected.customer_name"
		@close="bulkPayOpen = false"
		@done="
			bulkPayOpen = false;
			refreshAfterMoney();
		"
	/>

	<!-- Legacy parent-PE reallocation (finance only) -->
	<ParentReallocateDialog
		v-if="selected && canReallocate"
		:open="reallocateOpen"
		:company="activeCompany"
		:parent="selected.name"
		:parent-name="selected.customer_name"
		@close="reallocateOpen = false"
		@done="
			reallocateOpen = false;
			refreshAfterMoney();
		"
	/>

	<!-- Direct Sales Invoice Modal -->
	<NewDirectInvoiceModal
		:open="directInvoiceOpen"
		:initial-customer="selected?.name"
		:initial-customer-name="selected?.customer_name"
		@close="directInvoiceOpen = false"
		@created="pc?.refreshSelected()"
	/>
</template>
