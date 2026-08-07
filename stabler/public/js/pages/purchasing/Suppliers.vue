<script setup>
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import Select from "../../components/Select.vue";
import PartyPaymentModal from "../../components/PartyPaymentModal.vue";
import PartyCenter from "../../components/party/PartyCenter.vue";
import PartyKpiStrip from "../../components/party/PartyKpiStrip.vue";

const router = useRouter();
const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const { confirm } = useConfirm();
const toast = useToast();

const pc = ref(null);
const selected = ref(null);
const selectedDetail = ref(null);
const partyPayOpen = ref(false);

const SUPPLIER_TYPES = ["Company", "Individual", "Partnership"];
const supplierTypeOptions = computed(() => SUPPLIER_TYPES.map((st) => ({ value: st, label: t(st) })));

function blankSupplier() {
	return {
		supplier_name: "",
		supplier_type: "Company",
		supplier_group: "",
		country: "",
		email_id: "",
		mobile_no: "",
		tax_id: "",
		default_currency: "",
		default_price_list: "",
	};
}

const centerApi = {
	list: "stabler.api.purchasing.list_suppliers_with_balances",
	detail: "stabler.api.purchasing.supplier_detail",
	ledger: "stabler.api.purchasing.supplier_ledger",
	orders: "stabler.api.purchasing.list_purchase_orders",
	param: "supplier",
	nameField: "supplier_name",
	groupField: "supplier_group",
	invoiceDoctype: "Purchase Invoice",
	orderDoctype: "Purchase Order",
	ledgerReportKey: "supplier_ledger",
	// Payables: running balance = credit - debit (reversed vs. receivables).
	ledgerSign: -1,
};

const centerRoutes = {
	back: "/purchasing",
	vouchers: {
		"Payment Entry": "/money/payments/:name",
		"Purchase Invoice": "/purchasing/invoices/:name",
		"Purchase Order": "/purchasing/orders/:name",
		"Journal Entry": { path: "/money/journals", query: "open" },
	},
};

const centerCockpit = computed(() => ({
	method: "stabler.api.purchasing.payables_cockpit",
	keys: { total: "total_payable", today: "payments_paid_today", trend: "trend_8_weeks", top: "top_creditors" },
	labels: {
		total: t("Total payable"),
		today: t("Payments paid today"),
		trend: t("Payable Trend (Last 8 Weeks)"),
		trendSeries: t("Payables"),
		top: t("Top 10 Creditors"),
		empty: t("No creditors found."),
	},
}));

const centerLabels = computed(() => ({
	searchPlaceholder: t("Search suppliers… ⌘K"),
	groupLabel: t("Supplier group"),
	allGroups: t("All groups"),
	emptyTitle: t("No suppliers"),
	emptySubtitle: t("Add your first supplier to start recording bills and purchases."),
	emptyAction: t("Add supplier"),
	grandTotalLabel: t("All suppliers"),
	lifetimeLabel: t("Lifetime Purchases"),
	noOrdersTitle: t("No orders yet"),
	noOrdersSubtitle: t("No purchase orders have been registered for this supplier."),
	loadError: t("Failed to load suppliers."),
}));

const extraTabs = computed(() =>
	session.canAccessModule("tender")
		? [{ key: "quotations", label: t("Quotations"), badge: suppQuotations.value.length }]
		: [],
);

const paymentButtonTitle = computed(() => {
	if (!selected.value) return "";
	const who = selected.value.supplier_name || selected.value.name;
	const amount = formatMoney(
		selected.value.balance_acc ?? selected.value.balance_base ?? 0,
		selected.value.account_currency || session.currency,
		user.value.language,
	);
	return `${t("Payment")} — ${who} (${selected.value.name}) · ${amount}`;
});

function onSelect(row) {
	selected.value = row;
	if (!row) {
		selectedDetail.value = null;
		selectedExposure.value = null;
		suppQuotations.value = [];
		return;
	}
	loadExposure(row.name);
	loadSuppQuotations(row.name);
}

function onDetail(detail) {
	selectedDetail.value = detail;
}

function refreshAfterMoney() {
	pc.value?.reload();
	pc.value?.refreshSelected();
}

// Import position (open commitments + cash/bank paid split). Only populated when
// the company has the imports module on; otherwise stays null and the card hides.
const selectedExposure = ref(null);

// Load (or reload) the supplier's import position. Tenant-gated: a company with
// the imports module off returns {enabled:false} and the panel stays hidden.
async function loadExposure(supplierName) {
	selectedExposure.value = null;
	try {
		const exp = await call("stabler.api.purchasing.supplier_import_exposure", {
			supplier: supplierName,
			company: activeCompany.value,
		});
		if (exp && exp.enabled) selectedExposure.value = exp;
	} catch {
		selectedExposure.value = null;
	}
}

const exposureKpiItems = computed(() => {
	const s = selectedExposure.value?.summary;
	if (!s) return [];
	const cur = selected.value?.account_currency || session.currency;
	const lang = user.value.language;
	return [
		{ key: "open", label: t("Open commitment"), text: formatMoney(s.open_commitment || 0, cur, lang) },
		{
			key: "cash",
			label: t("Cash paid"),
			text: formatMoney(s.cash_paid || 0, cur, lang),
			note: s.cash_committed
				? `${s.cash_pct_paid}% · ${t("Balance")}: ${formatMoney(s.cash_balance || 0, cur, lang)}`
				: "",
		},
		{
			key: "bank",
			label: t("Bank paid"),
			text: formatMoney(s.bank_paid || 0, cur, lang),
			note: s.bank_committed
				? `${s.bank_pct_paid}% · ${t("Balance")}: ${formatMoney(s.bank_balance || 0, cur, lang)}`
				: "",
		},
		{
			key: "total",
			label: t("Total paid"),
			text: formatMoney(s.total_paid || 0, cur, lang),
			sev: s.reconciles_gl === false ? "crit" : "neutral",
		},
	];
});

// --- CI → Purchase Invoice conversion (WP-I6) ---------------------------------
// A two-step, GL-safe flow: openConvert previews (dry_run=1, writes nothing);
// confirmConvert creates the DRAFT Purchase Invoice (dry_run=0). Accounts posts
// it to GL — we never submit here.
const convertTarget = ref(null); // the CI commitment row being converted
const convertPreview = ref(null); // dry-run result from the backend
const convertBusy = ref(false);

async function openConvert(ci) {
	convertTarget.value = ci;
	convertPreview.value = null;
	convertBusy.value = true;
	try {
		convertPreview.value = await call("stabler.api.imports.convert_ci_to_purchase_invoice", {
			commercial_invoice: ci.name,
			company: activeCompany.value,
			dry_run: 1,
		});
	} catch (err) {
		toast.error(err?.message || t("Could not preview the conversion."));
		convertTarget.value = null;
	} finally {
		convertBusy.value = false;
	}
}

function closeConvert() {
	convertTarget.value = null;
	convertPreview.value = null;
	convertBusy.value = false;
}

async function confirmConvert() {
	if (!convertTarget.value || !convertPreview.value?.reconciles_agreed) return;
	convertBusy.value = true;
	try {
		const res = await call("stabler.api.imports.convert_ci_to_purchase_invoice", {
			commercial_invoice: convertTarget.value.name,
			company: activeCompany.value,
			dry_run: 0,
		});
		toast.success(
			res?.already_linked
				? t("This Commercial Invoice already has a Purchase Invoice.")
				: t("Draft Purchase Invoice created: {0}").replace("{0}", res.purchase_invoice),
		);
		closeConvert();
		if (selected.value) {
			loadExposure(selected.value.name);
			pc.value?.refreshSelected();
		}
	} catch (err) {
		toast.error(err?.message || t("Could not create the Purchase Invoice."));
	} finally {
		convertBusy.value = false;
	}
}

const suppQuotations = ref([]);
const suppQuotationsLoading = ref(false);

async function loadSuppQuotations(supplierName) {
	if (!supplierName || !activeCompany.value) return;
	suppQuotationsLoading.value = true;
	try {
		const res = await call("stabler.api.purchasing.supplier_quotation_history", {
			supplier: supplierName,
			company: activeCompany.value,
		});
		suppQuotations.value = res?.rows || [];
	} catch {
		suppQuotations.value = [];
	} finally {
		suppQuotationsLoading.value = false;
	}
}

const groupOptions = ref([]);
const currencyOptions = ref([]);
const priceListOptions = ref([]);
const optionsLoaded = ref(false);

const createOpen = ref(false);
const editMode = ref(false);
const editingName = ref("");
const submitting = ref(false);
const deleting = ref(false);
const submitError = ref("");
const form = ref(blankSupplier());

const formTitle = computed(() => (editMode.value ? t("Edit supplier") : t("New supplier")));
const canSubmit = computed(() => !!form.value.supplier_name.trim());

async function loadCreateOptions() {
	if (optionsLoaded.value) return;
	try {
		const [groups, currencies, priceLists] = await Promise.all([
			call("stabler.api.purchasing.list_supplier_groups", { limit: 200 }),
			call("stabler.api.sales.list_currencies"),
			call("stabler.api.sales.list_price_lists", { buying_only: 1, limit: 200 }),
		]);
		groupOptions.value = groups || [];
		currencyOptions.value = currencies || [];
		priceListOptions.value = priceLists || [];
		optionsLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || t("Failed to load options.");
	}
}

function openCreate() {
	editMode.value = false;
	editingName.value = "";
	form.value = blankSupplier();
	submitError.value = "";
	createOpen.value = true;
	loadCreateOptions();
}

function closeCreate() {
	if (submitting.value || deleting.value) return;
	createOpen.value = false;
}

async function openEdit(s) {
	editMode.value = true;
	editingName.value = s.name;
	submitError.value = "";
	createOpen.value = true;
	loadCreateOptions();
	try {
		form.value = await call("stabler.api.purchasing.get_supplier", { name: s.name });
	} catch (err) {
		submitError.value = err?.message || t("Failed to load supplier.");
	}
}

async function submitCreate() {
	submitError.value = "";
	const f = form.value;
	if (!f.supplier_name.trim()) return (submitError.value = t("Supplier name is required."));
	submitting.value = true;
	try {
		const payload = {
			supplier_name: f.supplier_name.trim(),
			supplier_type: f.supplier_type,
			supplier_group: f.supplier_group || null,
			country: f.country || null,
			email_id: f.email_id || null,
			mobile_no: f.mobile_no || null,
			tax_id: f.tax_id || null,
			default_price_list: f.default_price_list || null,
			default_currency: f.default_currency || null,
		};
		if (editMode.value) {
			await call("stabler.api.purchasing.update_supplier", { name: editingName.value, ...payload });
		} else {
			await call("stabler.api.purchasing.create_supplier", payload);
		}
		createOpen.value = false;
		await pc.value?.reload();
		if (editMode.value && selected.value?.name === editingName.value) {
			pc.value?.selectByName(editingName.value);
		}
	} catch (err) {
		submitError.value =
			err?.message || t(editMode.value ? "Failed to update supplier." : "Failed to create supplier.");
	} finally {
		submitting.value = false;
	}
}

async function deleteSupplier() {
	if (!editMode.value || !editingName.value) return;
	const ok = await confirm({
		title: t("Delete Supplier"),
		body: t("Delete supplier") + " " + editingName.value + "? " + t("This cannot be undone."),
		confirmLabel: t("Delete"),
		cancelLabel: t("Cancel"),
		danger: true,
	});
	if (!ok) return;
	deleting.value = true;
	try {
		await call("stabler.api.purchasing.delete_supplier", { name: editingName.value });
		toast.success(t("Supplier deleted."));
		createOpen.value = false;
		if (selected.value?.name === editingName.value) {
			selected.value = null;
		}
		await pc.value?.reload();
	} catch (err) {
		submitError.value = err?.message || t("Failed to delete supplier.");
	} finally {
		deleting.value = false;
	}
}
</script>

<template>
	<PartyCenter
		ref="pc"
		party-type="Supplier"
		:api="centerApi"
		:labels="centerLabels"
		:cockpit="centerCockpit"
		state-key="stabler.suppliers.listState"
		:routes="centerRoutes"
		:extra-tabs="extraTabs"
		:form-open="createOpen"
		:form-mode="editMode ? 'edit' : 'create'"
		:form-title="formTitle"
		:submitting="submitting"
		:deleting="deleting"
		:submit-error="submitError"
		:can-submit="canSubmit"
		:can-delete="editMode"
		@create="openCreate"
		@select="onSelect"
		@detail="onDetail"
		@close-form="closeCreate"
		@submit-form="submitCreate"
		@delete-form="deleteSupplier"
	>
		<template #actions="{ selected: sel, balance, balanceCurrency, exportLedger }">
			<!-- `pc-btn-txt`: başlık kaydırmada daralınca düşebilecek etiketler.
			     Payment işaretlenmez — tutarı her zaman görünür kalmalı. -->
			<button type="button" class="ds-btn" :title="t('Edit')" @click="openEdit(sel)">
				<i class="ti ti-pencil"></i><span class="pc-btn-txt">{{ t("Edit") }}</span>
			</button>
			<button type="button" class="ds-btn" :title="paymentButtonTitle" @click="partyPayOpen = true">
				<i class="ti ti-cash"></i>{{ t("Payment") }}
				<span class="font-monospace ms-1">{{ formatMoney(balance, balanceCurrency, user.language) }}</span>
			</button>
			<button
				type="button"
				class="ds-btn"
				:title="t('Professional Excel export of this ledger')"
				@click="exportLedger"
			>
				<i class="ti ti-file-spreadsheet"></i><span class="pc-btn-txt">{{ t("Statement") }}</span>
			</button>
		</template>

		<template #detail-banner="{ selected: sel }">
			<!-- Import Exposure (only when the imports module is on for this company) -->
			<section v-if="selectedExposure?.summary" class="ds-panel">
				<div class="ds-panel-head">
					<span class="ds-label">{{ t("Import Exposure") }}</span>
					<span
						v-if="!selectedExposure.summary.reconciles_gl"
						class="ds-chip"
						data-tone="crit"
						:title="t('Cash + bank paid does not match the GL total')"
					>{{ t("GL mismatch") }}</span>
				</div>
				<PartyKpiStrip :items="exposureKpiItems" :cols="4" :language="user.language" />
			</section>

			<!-- Open import commitments (CIs not yet invoiced) — WP-I6 -->
			<section v-if="selectedExposure?.commitments?.length" class="ds-panel">
				<div class="ds-panel-head">
					<span class="ds-label">{{ t("Open commitments") }}</span>
					<span class="ds-label">{{ selectedExposure.commitments.length }}</span>
				</div>
				<table class="ds-table">
					<thead>
						<tr>
							<th>{{ t("Commercial Invoice") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="ds-td-num">{{ t("Agreed total") }}</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="c in selectedExposure.commitments" :key="c.name">
							<td>
								<router-link
									:to="{ name: 'imports-commercial-invoice', params: { name: c.name } }"
									class="ds-mono"
								>
									{{ c.ci_number || c.name }}
								</router-link>
							</td>
							<td>
								<span class="badge" :class="getStatusBadgeClass('Commercial Invoice', c.status)">{{ t(c.status) }}</span>
							</td>
							<td class="ds-td-num">
								{{ formatMoney(c.agreed_total || 0, c.currency || sel.account_currency || session.currency, user.language) }}
							</td>
							<td class="ds-td-num">
								<button type="button" class="ds-btn" :disabled="convertBusy" @click="openConvert(c)">
									{{ t("Convert to Invoice") }}
								</button>
							</td>
						</tr>
					</tbody>
				</table>
			</section>
		</template>

		<template #extra-tabs="{ tab }">
			<template v-if="tab === 'quotations'">
				<table v-if="suppQuotationsLoading" class="ds-table">
					<SkeletonRows :rows="5" :cols="7" />
				</table>
				<EmptyState
					v-else-if="!suppQuotations.length"
					icon="ti-file-dollar"
					:title="t('No quotations yet')"
					:subtitle="t('No supplier quotations registered for this supplier.')"
				/>
				<table v-else class="ds-table">
					<thead>
						<tr>
							<th>{{ t("Quotation #") }}</th>
							<th>{{ t("Date") }}</th>
							<th>{{ t("Tender / deal") }}</th>
							<th class="ds-td-num">{{ t("Base total") }}</th>
							<th>{{ t("Valid till") }}</th>
							<th>{{ t("Status") }}</th>
							<th>{{ t("Result") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="q in suppQuotations"
							:key="q.name"
							:style="{ cursor: q.deal || q.custom_crm_deal ? 'pointer' : 'default' }"
							@click="q.deal || q.custom_crm_deal ? router.push({ path: '/tender/sourcing', query: { deal: q.deal || q.custom_crm_deal } }) : null"
						>
							<td><span class="ds-mono">{{ q.name }}</span></td>
							<td>{{ q.transaction_date ? formatDate(q.transaction_date) : "—" }}</td>
							<td>
								<span v-if="q.deal || q.custom_crm_deal">
									<i class="ti ti-target me-1 text-primary"></i>
									{{ q.deal_label || q.deal || q.custom_crm_deal }}
								</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td class="ds-td-num">
								{{ formatMoney(q.base_grand_total || q.grand_total, q.currency || session.currency, user.language) }}
							</td>
							<td>{{ q.valid_till ? formatDate(q.valid_till) : "—" }}</td>
							<td>
								<span class="badge" :class="getStatusBadgeClass('Supplier Quotation', q.status)">{{ t(q.status) }}</span>
							</td>
							<td>
								<span v-if="q.result === 'won'" class="ds-chip" data-tone="ok">{{ t("Won") }}</span>
								<span v-else-if="q.result === 'lost'" class="ds-chip">{{ t("Lost") }}</span>
								<span v-else class="ds-chip" data-tone="soon">{{ t("Open") }}</span>
							</td>
						</tr>
					</tbody>
				</table>
			</template>
		</template>

		<template #form-fields>
			<div class="row g-3">
				<div class="col-12">
					<label class="form-label">{{ t("Supplier name") }} <span class="text-danger">*</span></label>
					<input v-model="form.supplier_name" type="text" class="form-control" autofocus />
				</div>
				<div class="col-md-6">
					<label class="form-label">{{ t("Type") }}</label>
					<Select v-model="form.supplier_type" :options="supplierTypeOptions" />
				</div>
				<div class="col-md-6">
					<label class="form-label">{{ t("Tax ID") }}</label>
					<input v-model="form.tax_id" type="text" class="form-control" />
				</div>
				<div class="col-md-6">
					<label class="form-label">{{ t("Supplier group") }}</label>
					<Select v-model="form.supplier_group" :options="groupOptions" value-key="name" label-key="name" :placeholder="t('— default —')" />
				</div>
				<div class="col-md-6">
					<label class="form-label">{{ t("Country") }}</label>
					<input v-model="form.country" type="text" class="form-control" />
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
					<Select v-model="form.default_price_list" :options="priceListOptions" value-key="name" :placeholder="t('— global default —')">
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
					<Select v-model="form.default_currency" class="font-monospace" :options="currencyOptions" value-key="name" :placeholder="t('— company default —')">
						<template #option="{ option: c }">
							{{ c.name }}<template v-if="c.symbol"> ({{ c.symbol }})</template>
						</template>
						<template #selected="{ option: c }">
							{{ c.name }}<template v-if="c.symbol"> ({{ c.symbol }})</template>
						</template>
					</Select>
				</div>
			</div>
		</template>
	</PartyCenter>

	<!-- Payment Entry Modal -->
	<PartyPaymentModal
		v-if="selected"
		:open="partyPayOpen"
		party-type="Supplier"
		:party="selected.name"
		:party-name="selected.supplier_name"
		:company="activeCompany"
		@close="partyPayOpen = false"
		@paid="partyPayOpen = false; refreshAfterMoney();"
	/>

	<!-- CI → Purchase Invoice convert (WP-I6): preview (dry-run), then confirm -->
	<template v-if="convertTarget">
		<div class="modal-backdrop fade show" @click="closeConvert"></div>
		<div class="modal fade show d-block" tabindex="-1" role="dialog">
			<div class="modal-dialog modal-dialog-centered" role="document">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("Convert to Purchase Invoice") }}</h5>
						<button type="button" class="btn-close" :aria-label="t('Close')" @click="closeConvert"></button>
					</div>
					<div class="modal-body">
						<div v-if="convertBusy && !convertPreview" class="text-center py-4 text-secondary">
							<span class="spinner-border spinner-border-sm me-2"></span>{{ t("Previewing…") }}
						</div>
						<template v-else-if="convertPreview">
							<div v-if="convertPreview.already_linked" class="alert alert-info mb-0">
								{{ t("This Commercial Invoice already has a Purchase Invoice.") }}
							</div>
							<template v-else>
								<div class="mb-3">
									<div class="d-flex justify-content-between py-1">
										<span class="text-secondary">{{ t("Commercial Invoice") }}</span>
										<span class="fw-medium">{{ convertTarget.ci_number || convertTarget.name }}</span>
									</div>
									<div class="d-flex justify-content-between py-1">
										<span class="text-secondary">{{ t("Agreed total") }}</span>
										<span class="font-monospace">{{ formatMoney(convertPreview.agreed_total || 0, convertPreview.currency, user.language) }}</span>
									</div>
									<div class="d-flex justify-content-between py-1">
										<span class="text-secondary">{{ t("Invoice lines total") }}</span>
										<span class="font-monospace">{{ formatMoney(convertPreview.lines_total || 0, convertPreview.currency, user.language) }}</span>
									</div>
								</div>
								<div v-if="!convertPreview.reconciles_agreed" class="alert alert-warning">
									{{ convertPreview.warning || t("Invoice total does not match the agreed total.") }}
								</div>
								<div v-if="convertPreview.advance_plan && convertPreview.advance_plan.allocations.length" class="mb-2">
									<div class="text-secondary small text-uppercase fw-semibold mb-1">{{ t("Advance allocation") }}</div>
									<div
										v-for="a in convertPreview.advance_plan.allocations"
										:key="a.payment_entry"
										class="d-flex justify-content-between small py-1"
									>
										<span class="font-monospace">{{ a.payment_entry }}</span>
										<span class="font-monospace">{{ formatMoney(a.amount || 0, convertPreview.currency, user.language) }}</span>
									</div>
									<div class="d-flex justify-content-between py-1 border-top mt-1">
										<span class="text-secondary">{{ t("Remaining after advances") }}</span>
										<span class="font-monospace">{{ formatMoney(convertPreview.advance_plan.outstanding_after || 0, convertPreview.currency, user.language) }}</span>
									</div>
								</div>
								<p class="text-secondary small mb-0">
									{{ t("A draft Purchase Invoice is created for review — it is not posted to the ledger until Accounts submits it. The customs docs value is excluded.") }}
								</p>
							</template>
						</template>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-link link-secondary" :disabled="convertBusy" @click="closeConvert">
							{{ t("Cancel") }}
						</button>
						<button
							type="button"
							class="btn btn-primary"
							:disabled="convertBusy || !convertPreview || !convertPreview.reconciles_agreed || convertPreview.already_linked"
							@click="confirmConvert"
						>
							<span v-if="convertBusy" class="spinner-border spinner-border-sm me-2"></span>
							<i v-else class="ti ti-check me-1"></i>{{ t("Create draft invoice") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</template>
</template>
