<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import {
	listPromoPlans,
	createPromoPlan,
	getPromoPlan,
	updatePromoPlan,
} from "../../api/marketing.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import Typeahead from "../../components/Typeahead.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const { activeCompany, user, companies } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const search = ref("");

const drawerOpen = ref(false);
const drawerMode = ref("create"); // "create" | "edit"
const saving = ref(false);
const loadingDetail = ref(false);
const formError = ref("");
const form = ref(emptyForm());

const PLAN_STATUSES = ["Draft", "Active", "Closed"];

function emptyForm() {
	return {
		name: "",
		campaign_name: "",
		company: "",
		plan_type: "TPR",
		channel: "",
		status: "Draft",
		budget: null,
		start_date: "",
		end_date: "",
		trigger_item: "",
		trigger_item_display: "",
		notes: "",
	};
}

const currency = computed(
	() => session.companyMeta?.(activeCompany.value)?.default_currency
		|| session.currentCompany?.default_currency
		|| "UZS"
);
const lang = computed(() => user.value?.language || "en");

const PLAN_TYPES = ["TPR", "BOGO", "Display", "Sampling"];
const CHANNELS = ["GT", "MT", "Horeca", "B2B"];

const statusOptions = computed(() =>
	PLAN_STATUSES.map((s) => ({ value: s, label: t(s) }))
);
const channelOptions = computed(() => [
	{ value: "", label: t("—") },
	...CHANNELS.map((ch) => ({ value: ch, label: ch })),
]);

async function load() {
	if (!activeCompany.value) {
		rows.value = [];
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		rows.value = await listPromoPlans({
			filters: {
				company: activeCompany.value,
				search: search.value || undefined,
			},
		});
	} catch (e) {
		error.value = e?.message || t("Something went wrong");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);

let searchTimer = null;
watch(search, () => {
	if (searchTimer) clearTimeout(searchTimer);
	searchTimer = setTimeout(load, 250);
});

function statusClass(status) {
	if (status === "Active") return "bg-success-lt";
	if (status === "Closed") return "bg-secondary-lt";
	return "bg-yellow-lt";
}

function planTypeClass(pt) {
	if (pt === "TPR") return "bg-blue-lt";
	if (pt === "BOGO") return "bg-purple-lt";
	if (pt === "Display") return "bg-cyan-lt";
	if (pt === "Sampling") return "bg-pink-lt";
	return "bg-secondary-lt";
}

function openCreate() {
	drawerMode.value = "create";
	form.value = emptyForm();
	form.value.company = activeCompany.value || "";
	formError.value = "";
	drawerOpen.value = true;
}

async function openEdit(name) {
	drawerMode.value = "edit";
	form.value = emptyForm();
	formError.value = "";
	drawerOpen.value = true;
	loadingDetail.value = true;
	try {
		const doc = await getPromoPlan(name);
		form.value = {
			name: doc.name || "",
			campaign_name: doc.campaign_name || "",
			company: doc.company || "",
			plan_type: doc.plan_type || "TPR",
			channel: doc.channel || "",
			status: doc.status || "Draft",
			budget: doc.budget ?? null,
			start_date: doc.start_date || "",
			end_date: doc.end_date || "",
			trigger_item: doc.trigger_item || "",
			trigger_item_display: doc.trigger_item || "",
			notes: doc.notes || "",
		};
	} catch (e) {
		formError.value = e?.message || t("Failed to load promo plan.");
	} finally {
		loadingDetail.value = false;
	}
}

function closeDrawer() {
	drawerOpen.value = false;
}

const drawerTitle = computed(() =>
	drawerMode.value === "edit" ? t("Edit Promo Plan") : t("New Promo Plan")
);

async function searchItem(q) {
	const items = await call("stabler.api.inventory.list_items", { search: q, limit: 25 });
	return items || [];
}

function pickItem(item) {
	form.value.trigger_item = item.name;
	form.value.trigger_item_display = `${item.item_code} — ${item.item_name || ""}`.trim();
}

function clearItem() {
	form.value.trigger_item = "";
	form.value.trigger_item_display = "";
}

async function submitForm() {
	formError.value = "";
	if (!form.value.campaign_name || !form.value.company
		|| !form.value.plan_type || !form.value.start_date || !form.value.end_date) {
		formError.value = t("Please fill all required fields.");
		return;
	}
	if (form.value.end_date < form.value.start_date) {
		formError.value = t("End Date must be on or after Start Date.");
		return;
	}
	saving.value = true;
	try {
		const payload = {
			campaign_name: form.value.campaign_name,
			company: form.value.company,
			plan_type: form.value.plan_type,
			channel: form.value.channel || null,
			budget: form.value.budget,
			start_date: form.value.start_date,
			end_date: form.value.end_date,
			trigger_item: form.value.trigger_item || null,
			notes: form.value.notes || null,
		};
		if (drawerMode.value === "edit") {
			payload.status = form.value.status;
			await updatePromoPlan(form.value.name, payload);
		} else {
			await createPromoPlan(payload);
		}
		drawerOpen.value = false;
		await load();
	} catch (e) {
		formError.value = e?.message
			|| (drawerMode.value === "edit"
				? t("Failed to update promo plan.")
				: t("Failed to create promo plan."));
	} finally {
		saving.value = false;
	}
}
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap gap-2 align-items-center">
			<h3 class="card-title mb-0">{{ t("Promo Plans") }}</h3>
			<div class="ms-auto d-flex gap-2 align-items-center" style="min-width: 320px">
				<input
					v-model="search"
					type="search"
					class="form-control form-control-sm"
					:placeholder="t('Search campaigns…')"
				/>
				<button type="button" class="btn btn-primary btn-sm" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New Plan") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-discount"
			:title="t('No promo plans yet')"
			:description="t('Create a plan to start tracking campaign budget and ROI.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Campaign") }}</th>
						<th>{{ t("Type") }}</th>
						<th>{{ t("Channel") }}</th>
						<th>{{ t("Status") }}</th>
						<th class="text-end">{{ t("Budget") }}</th>
						<th>{{ t("Start") }}</th>
						<th>{{ t("End") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="r in rows"
						:key="r.name"
						style="cursor: pointer"
						@click="openEdit(r.name)"
					>
						<td>
							<div>{{ r.campaign_name }}</div>
							<div class="small text-secondary font-monospace">{{ r.name }}</div>
						</td>
						<td>
							<span class="badge" :class="planTypeClass(r.plan_type)">{{ r.plan_type }}</span>
						</td>
						<td>{{ r.channel || "—" }}</td>
						<td>
							<span class="badge" :class="statusClass(r.status)">{{ t(r.status) }}</span>
						</td>
						<td class="text-end font-monospace">
							{{ formatMoney(r.budget, currency, lang) }}
						</td>
						<td>{{ formatDateTime(r.start_date) || "—" }}</td>
						<td>{{ formatDateTime(r.end_date) || "—" }}</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<div v-if="drawerOpen" class="offcanvas-backdrop fade show" @click="closeDrawer"></div>
	<div
		class="offcanvas offcanvas-end"
		:class="{ show: drawerOpen }"
		tabindex="-1"
		style="visibility: visible; width: 520px"
		:style="{ transform: drawerOpen ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">{{ drawerTitle }}</h5>
			<button type="button" class="btn-close" @click="closeDrawer" :aria-label="t('Close')"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="loadingDetail" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<template v-else>
				<div v-if="formError" class="alert alert-danger">{{ formError }}</div>

				<div class="mb-3">
					<label class="form-label required">{{ t("Campaign Name") }}</label>
					<input v-model="form.campaign_name" type="text" class="form-control" />
				</div>

				<div class="mb-3">
					<label class="form-label required">{{ t("Company") }}</label>
					<Select
						v-model="form.company"
						:options="companies"
						value-key="name"
						:placeholder="t('Select company')"
						:disabled="drawerMode === 'edit'"
					>
						<template #option="{ option }">{{ option.company_name || option.name }}</template>
						<template #selected="{ option }">{{ option.company_name || option.name }}</template>
					</Select>
				</div>

				<div class="row g-2">
					<div class="col-md-6 mb-3">
						<label class="form-label required">{{ t("Plan Type") }}</label>
						<Select v-model="form.plan_type" :options="PLAN_TYPES" />
					</div>
					<div class="col-md-6 mb-3">
						<label class="form-label">{{ t("Channel") }}</label>
						<Select v-model="form.channel" :options="channelOptions" />
					</div>
				</div>

				<div v-if="drawerMode === 'edit'" class="mb-3">
					<label class="form-label required">{{ t("Status") }}</label>
					<Select v-model="form.status" :options="statusOptions" />
				</div>

				<div class="mb-3">
					<label class="form-label">{{ t("Budget") }}</label>
					<MoneyInput
						v-model="form.budget"
						:currency="currency"
						:language="lang"
					/>
				</div>

				<div class="row g-2">
					<div class="col-md-6 mb-3">
						<label class="form-label required">{{ t("Start Date") }}</label>
						<DateInput v-model="form.start_date" />
					</div>
					<div class="col-md-6 mb-3">
						<label class="form-label required">{{ t("End Date") }}</label>
						<DateInput v-model="form.end_date" />
					</div>
				</div>

				<div class="mb-3">
					<label class="form-label">{{ t("Trigger Item") }}</label>
					<Typeahead
						:model-value="form.trigger_item"
						:display="form.trigger_item_display"
						:search="searchItem"
						:placeholder="t('Search items…')"
						:no-results-text="t('No matches found')"
						@pick="pickItem"
						@clear="clearItem"
					>
						<template #option="{ item }">
							<div class="d-flex justify-content-between">
								<span>{{ item.item_code }}</span>
								<span class="text-secondary small">{{ item.item_name }}</span>
							</div>
						</template>
					</Typeahead>
				</div>

				<div class="mb-3">
					<label class="form-label">{{ t("Notes") }}</label>
					<textarea v-model="form.notes" class="form-control" rows="3"></textarea>
				</div>

				<div class="d-flex gap-2 mt-4">
					<button type="button" class="btn btn-primary" :disabled="saving" @click="submitForm">
						<span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
						{{ drawerMode === "edit" ? t("Save Changes") : t("Create Plan") }}
					</button>
					<button type="button" class="btn btn-link" @click="closeDrawer">{{ t("Cancel") }}</button>
				</div>
			</template>
		</div>
	</div>
</template>
