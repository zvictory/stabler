<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import DateInput from "../../components/DateInput.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import StatusBadge from "../../components/StatusBadge.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
const { confirm } = useConfirm();
useEscapeBack(null, "/imports/customs");

const docName = computed(() => (route.params.name ? String(route.params.name) : null));
const isCreate = computed(() => !docName.value);

const loading = ref(false);
const saving = ref(false);
const uploading = ref(false);
const error = ref("");
const form = ref(blankForm());

function blankForm() {
	return {
		name: null,
		modified: null,
		gtd_number: "",
		commercial_invoice: "",
		container: "",
		declaration_date: "",
		customs_office: "",
		cleared_date: "",
		status: "Draft",
		customs_value_usd: 0,
		customs_value_uzs: 0,
		duty_amount: 0,
		vat_amount: 0,
		excise_amount: 0,
		total_duties: 0,
		document: "",
		notes: "",
		allowed_transitions: [],
		lines: [],
	};
}

const totalDuties = computed(() =>
	Number(form.value.duty_amount || 0) + Number(form.value.vat_amount || 0) + Number(form.value.excise_amount || 0)
);

const itemsList = ref([]);
async function loadItemsList() {
	try {
		itemsList.value = await call("stabler.api.inventory.list_items", { limit: 500 });
	} catch (_) {
		itemsList.value = [];
	}
}
function onItemSelect(row) {
	const found = itemsList.value.find((i) => (i.item_code || i.name) === row.item_code);
	if (found) {
		row.item_name = found.item_name || found.name;
		if (!row.description) row.description = found.item_name || "";
	}
}
function addLine() {
	form.value.lines.push({ item_code: "", item_name: "", description: "", hs_code: "", country_of_origin: "", gross_weight_kg: 0, net_weight_kg: 0, box_qty: 0, statistical_value_usd: 0, duty_rate_pct: 0, excise_rate_pct: 0, vat_rate_pct: 12 });
}
function removeLine(i) {
	form.value.lines.splice(i, 1);
}
async function loadDoc() {
	if (isCreate.value) {
		form.value = blankForm();
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		const d = await importsApi.getCustomsDeclaration(docName.value);
		form.value = { ...blankForm(), ...d, lines: (d.lines || []).map((l) => ({ ...l })) };
	} catch (err) {
		error.value = err?.message || t("Failed to load the declaration.");
	} finally {
		loading.value = false;
	}
}

function buildValues() {
	return {
		gtd_number: form.value.gtd_number || undefined,
		commercial_invoice: form.value.commercial_invoice || undefined,
		container: form.value.container || undefined,
		declaration_date: form.value.declaration_date || undefined,
		customs_office: form.value.customs_office,
		cleared_date: form.value.cleared_date || undefined,
		customs_value_usd: Number(form.value.customs_value_usd || 0),
		customs_value_uzs: Number(form.value.customs_value_uzs || 0),
		duty_amount: Number(form.value.duty_amount || 0),
		vat_amount: Number(form.value.vat_amount || 0),
		excise_amount: Number(form.value.excise_amount || 0),
		document: form.value.document || undefined,
		notes: form.value.notes,
	};
}

function linesPayload() {
	return form.value.lines
		.filter((l) => l.item_code || l.hs_code || l.description)
		.map((l) => ({
			item_code: l.item_code || undefined,
			description: l.description || undefined,
			hs_code: l.hs_code || undefined,
			country_of_origin: l.country_of_origin || undefined,
			gross_weight_kg: Number(l.gross_weight_kg || 0),
			net_weight_kg: Number(l.net_weight_kg || 0),
			box_qty: Number(l.box_qty || 0),
			statistical_value_usd: Number(l.statistical_value_usd || 0),
			duty_rate_pct: Number(l.duty_rate_pct || 0),
			excise_rate_pct: Number(l.excise_rate_pct || 0),
			vat_rate_pct: Number(l.vat_rate_pct || 0),
		}));
}

async function save() {
	saving.value = true;
	try {
		if (isCreate.value) {
			const res = await importsApi.createCustomsDeclaration({ company: activeCompany.value, values: buildValues(), lines: linesPayload() });
			toast.success(t("Declaration created."));
			router.replace("/imports/customs/" + res.name);
		} else {
			await importsApi.updateCustomsDeclaration({ name: docName.value, values: buildValues(), lines: linesPayload(), modified: form.value.modified });
			toast.success(t("Declaration saved."));
			await loadDoc();
		}
	} catch (err) {
		toast.error(err?.message || t("Save failed."));
	} finally {
		saving.value = false;
	}
}

async function onDocSelect(e) {
	const file = e.target.files?.[0];
	if (!file) return;
	uploading.value = true;
	try {
		const fd = new FormData();
		fd.append("file", file);
		fd.append("is_private", "1");
		const csrf = (window.__STABLER__ && window.__STABLER__.csrfToken) || "";
		const res = await fetch("/api/method/upload_file", {
			method: "POST",
			credentials: "same-origin",
			body: fd,
			headers: { "X-Frappe-CSRF-Token": csrf },
		});
		if (!res.ok) throw new Error(`${t("Upload failed")}: ${res.status}`);
		const json = await res.json();
		form.value.document = json.message?.file_url || "";
		toast.success(t("Document attached."));
	} catch (err) {
		toast.error(err?.message || t("Upload failed"));
	} finally {
		uploading.value = false;
		e.target.value = "";
	}
}

async function advanceStatus(nextStatus) {
	const backward = !form.value.allowed_transitions.includes(nextStatus);
	let reason = null;
	if (backward) {
		reason = window.prompt(t("Reason for the status correction:"));
		if (!reason) return;
	} else {
		const ok = await confirm({
			title: t("Change status"),
			body: t("Move this declaration to {status}?", { status: t(nextStatus) }),
			confirmLabel: t("Confirm"),
		});
		if (!ok) return;
	}
	try {
		await importsApi.setCustomsDeclarationStatus(docName.value, nextStatus, reason);
		toast.success(t("Status updated."));
		await loadDoc();
	} catch (err) {
		toast.error(err?.message || t("Status change failed."));
	}
}

onMounted(() => {
	loadItemsList();
	loadDoc();
});
watch(docName, loadDoc);
</script>

<template>
	<div>
		<div class="d-flex align-items-center mb-3">
			<button type="button" class="btn btn-ghost-secondary btn-icon me-2" @click="router.push('/imports/customs')">
				<i class="ti ti-arrow-left"></i>
			</button>
			<div>
				<h2 class="page-title mb-0">{{ isCreate ? t("New customs declaration") : (form.gtd_number || form.name) }}</h2>
				<div v-if="!isCreate" class="text-secondary small"><StatusBadge doctype="Customs Declaration" :status="form.status" /></div>
			</div>
			<div class="ms-auto">
				<button type="button" class="btn btn-primary" :disabled="saving" @click="save">
					<i class="ti ti-device-floppy me-1"></i>{{ t("Save") }}
				</button>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<!-- Status action bar -->
		<div v-if="!isCreate" class="card mb-3">
			<div class="card-body d-flex align-items-center flex-wrap gap-2">
				<span class="text-secondary small">{{ t("Status") }}:</span>
				<StatusBadge doctype="Customs Declaration" :status="form.status" />
				<div class="ms-auto d-flex gap-2 flex-wrap">
					<button
						v-for="ns in form.allowed_transitions.filter((s) => s !== 'Rejected')"
						:key="ns"
						type="button"
						class="btn btn-outline-primary btn-sm"
						@click="advanceStatus(ns)"
					>
						<i class="ti ti-arrow-right me-1"></i>{{ t(ns) }}
					</button>
					<button
						v-if="form.allowed_transitions.includes('Rejected')"
						type="button"
						class="btn btn-outline-danger btn-sm"
						@click="advanceStatus('Rejected')"
					>
						{{ t("Reject") }}
					</button>
				</div>
			</div>
		</div>

		<!-- Header -->
		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title">{{ t("Declaration") }}</h3></div>
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-4">
						<label class="form-label">{{ t("GTD number") }}</label>
						<input v-model="form.gtd_number" type="text" class="form-control font-monospace" placeholder="26010/110726/1234567" />
					</div>
					<div class="col-md-4">
						<label class="form-label">{{ t("Commercial Invoice") }}</label>
						<input v-model="form.commercial_invoice" type="text" class="form-control font-monospace" />
					</div>
					<div class="col-md-4">
						<label class="form-label">{{ t("Container") }}</label>
						<input v-model="form.container" type="text" class="form-control font-monospace" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Declaration date") }}</label>
						<DateInput v-model="form.declaration_date" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Cleared date") }}</label>
						<DateInput v-model="form.cleared_date" />
					</div>
					<div class="col-md-6">
						<label class="form-label">{{ t("Customs office") }}</label>
						<input v-model="form.customs_office" type="text" class="form-control" />
					</div>
				</div>
			</div>
		</div>

		<!-- Valuation -->
		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title">{{ t("Valuation & duties") }}</h3></div>
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-3"><label class="form-label">{{ t("Customs value (USD)") }}</label><MoneyInput v-model="form.customs_value_usd" currency="USD" :language="user.language" size="sm" /></div>
					<div class="col-md-3"><label class="form-label">{{ t("Customs value (UZS)") }}</label><MoneyInput v-model="form.customs_value_uzs" currency="UZS" :language="user.language" size="sm" /></div>
					<div class="col-md-2"><label class="form-label">{{ t("Duty") }}</label><MoneyInput v-model="form.duty_amount" :language="user.language" size="sm" /></div>
					<div class="col-md-2"><label class="form-label">{{ t("VAT") }}</label><MoneyInput v-model="form.vat_amount" :language="user.language" size="sm" /></div>
					<div class="col-md-2"><label class="form-label">{{ t("Excise") }}</label><MoneyInput v-model="form.excise_amount" :language="user.language" size="sm" /></div>
				</div>
				<div class="d-flex justify-content-end mt-2">
					<span class="text-secondary me-2">{{ t("Total duties") }}:</span>
					<strong class="font-monospace">{{ totalDuties.toFixed(0) }}</strong>
				</div>
			</div>
		</div>

		<!-- Lines -->
		<div class="card mb-3">
			<div class="card-header">
				<h3 class="card-title">{{ t("Declaration lines") }}</h3>
				<div class="card-actions">
					<button type="button" class="btn btn-outline-secondary btn-sm" @click="addLine"><i class="ti ti-plus me-1"></i>{{ t("Add line") }}</button>
				</div>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter card-table">
					<thead>
						<tr>
							<th style="width: 20%">{{ t("Item") }}</th>
							<th style="width: 90px">{{ t("HS code") }}</th>
							<th style="width: 90px">{{ t("Origin") }}</th>
							<th class="text-end" style="width: 90px">{{ t("Net kg") }}</th>
							<th class="text-end" style="width: 110px">{{ t("Stat. value") }}</th>
							<th class="text-end" style="width: 80px">{{ t("Duty %") }}</th>
							<th class="text-end" style="width: 80px">{{ t("Excise %") }}</th>
							<th class="text-end" style="width: 80px">{{ t("VAT %") }}</th>
							<th style="width: 40px"></th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(row, i) in form.lines" :key="i">
							<td>
								<select v-model="row.item_code" class="form-select form-select-sm fw-semibold" @change="onItemSelect(row)">
									<option value="">— {{ t("Select product") }} —</option>
									<option v-for="it in itemsList" :key="it.item_code || it.name" :value="it.item_code || it.name">
										{{ it.item_code || it.name }} — {{ it.item_name }}
									</option>
								</select>
							</td>
							<td><input v-model="row.hs_code" type="text" class="form-control form-control-sm" /></td>
							<td><input v-model="row.country_of_origin" type="text" class="form-control form-control-sm" /></td>
							<td><input v-model.number="row.net_weight_kg" type="number" class="form-control form-control-sm text-end" /></td>
							<td><MoneyInput v-model="row.statistical_value_usd" currency="USD" :language="user.language" size="sm" hide-currency /></td>
							<td><input v-model.number="row.duty_rate_pct" type="number" class="form-control form-control-sm text-end" /></td>
							<td><input v-model.number="row.excise_rate_pct" type="number" class="form-control form-control-sm text-end" /></td>
							<td><input v-model.number="row.vat_rate_pct" type="number" class="form-control form-control-sm text-end" /></td>
							<td class="text-center align-middle"><button type="button" class="btn btn-ghost-danger btn-icon btn-sm" @click="removeLine(i)"><i class="ti ti-trash"></i></button></td>
						</tr>
						<tr v-if="!form.lines.length"><td colspan="9" class="text-secondary text-center py-3">{{ t("No lines yet.") }}</td></tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- Document + notes -->
		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title">{{ t("Document & notes") }}</h3></div>
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-6">
						<label class="form-label">{{ t("Scanned declaration") }}</label>
						<input type="file" class="form-control" :disabled="uploading" @change="onDocSelect" />
						<div v-if="uploading" class="form-hint text-secondary">{{ t("Uploading…") }}</div>
						<div v-else-if="form.document" class="form-hint">
							<a :href="form.document" target="_blank" rel="noopener"><i class="ti ti-paperclip me-1"></i>{{ t("View attached document") }}</a>
						</div>
					</div>
					<div class="col-md-6">
						<label class="form-label">{{ t("Notes") }}</label>
						<textarea v-model="form.notes" class="form-control" rows="2"></textarea>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
