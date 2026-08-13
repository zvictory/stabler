<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import DateInput from "../../components/DateInput.vue";
import StatusBadge from "../../components/StatusBadge.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
const { confirm } = useConfirm();
useEscapeBack(null, "/imports/grn-checklists");

const docName = computed(() => (route.params.name ? String(route.params.name) : null));

const loading = ref(false);
const error = ref("");
const submitting = ref(false);
const doc = ref(null);

const MANAGER_ROLES = ["Imports Manager", "System Manager", "Stabler Admin"];
const isManager = computed(() => (session.roles || []).some((r) => MANAGER_ROLES.includes(r)));

const isDraft = computed(() => doc.value && doc.value.docstatus === 0);
const validVetCert = computed(() => doc.value && doc.value.has_valid_vet_cert);

// Vet certificate inline create form.
const showVetForm = ref(false);
const vetForm = ref(blankVetForm());
function blankVetForm() {
	return { certificate_number: "", issuing_authority: "", issue_date: "", expiry_date: "" };
}

function pct(v) {
	return Math.max(0, Math.min(100, Number(v || 0)));
}
function progressClass(v) {
	const p = pct(v);
	if (p >= 100) return "bg-green";
	if (p > 0) return "bg-blue";
	return "bg-secondary";
}

async function load() {
	if (!docName.value) return;
	loading.value = true;
	error.value = "";
	try {
		doc.value = await importsApi.getGrnChecklist(docName.value);
	} catch (err) {
		error.value = err?.message || t("Failed to load the GRN checklist.");
	} finally {
		loading.value = false;
	}
}

async function submitGrn() {
	if (!validVetCert.value && !doc.value.vet_cert_override) {
		const ok = await confirm({
			title: t("Missing veterinary certificate"),
			body: t("No approved veterinary certificate exists for this shipment. The submit will be rejected unless an Imports Manager set an override. Continue anyway?"),
			confirmLabel: t("Try to submit"),
		});
		if (!ok) return;
	} else {
		const ok = await confirm({
			title: t("Complete GRN"),
			body: t("Submit this GRN checklist? This closes receiving and drafts a landed cost voucher."),
			confirmLabel: t("Submit GRN"),
		});
		if (!ok) return;
	}
	submitting.value = true;
	try {
		await importsApi.submitGrnChecklist(docName.value);
		toast.success(t("GRN checklist submitted."));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not submit the GRN checklist."));
	} finally {
		submitting.value = false;
	}
}

function newTruckReceipt() {
	router.push({ path: "/imports/truck-receipts/new", query: { grn: docName.value } });
}
function openTruckReceipt(name) {
	router.push("/imports/truck-receipts/" + name);
}

async function saveVetCert() {
	if (!vetForm.value.certificate_number) {
		toast.error(t("A certificate number is required."));
		return;
	}
	try {
		await importsApi.createVetCertificate({
			company: activeCompany.value,
			values: {
				commercial_invoice: doc.value.commercial_invoice,
				certificate_number: vetForm.value.certificate_number,
				issuing_authority: vetForm.value.issuing_authority || undefined,
				issue_date: vetForm.value.issue_date || undefined,
				expiry_date: vetForm.value.expiry_date || undefined,
			},
		});
		toast.success(t("Veterinary certificate added."));
		showVetForm.value = false;
		vetForm.value = blankVetForm();
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not add the veterinary certificate."));
	}
}

async function setVetStatus(cert, status) {
	let reason = null;
	if (status === "Rejected") {
		reason = window.prompt(t("Rejection reason:"));
		if (!reason) return;
	}
	try {
		await importsApi.setVetCertificateStatus(cert.name, status, reason);
		toast.success(t("Veterinary certificate updated."));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not update the certificate."));
	}
}

async function addLcv() {
	const ok = await confirm({
		title: t("Add landed cost voucher"),
		body: t("Draft an additional landed cost voucher for late costs on this GRN?"),
		confirmLabel: t("Create voucher"),
	});
	if (!ok) return;
	try {
		await importsApi.createAdditionalLcv(docName.value);
		toast.success(t("Landed cost voucher drafted."));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not create the voucher."));
	}
}

onMounted(load);
watch(docName, load);
watch(activeCompany, load);
</script>

<template>
	<div>
		<div class="d-flex align-items-center mb-3">
			<button type="button" class="btn btn-ghost-secondary btn-icon me-2" @click="router.push('/imports/grn-checklists')">
				<i class="ti ti-arrow-left"></i>
			</button>
			<div>
				<h2 class="page-title mb-0">{{ doc ? doc.name : t("GRN checklist") }}</h2>
				<div v-if="doc" class="text-secondary small">
					<StatusBadge doctype="GRN Checklist" :status="doc.receipt_status" />
					<StatusBadge class="ms-1" doctype="GRN Checklist" :docstatus="doc.docstatus" />
				</div>
			</div>
			<div v-if="doc && isDraft" class="ms-auto">
				<button type="button" class="btn btn-primary" :disabled="submitting" @click="submitGrn">
					<i class="ti ti-checkbox me-1"></i>{{ t("Submit GRN") }}
				</button>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>
		<div v-if="loading" class="text-secondary">{{ t("Loading…") }}</div>

		<template v-if="doc && !loading">
			<!-- Header -->
			<div class="card mb-3">
				<div class="card-body">
					<dl class="row mb-0">
						<dt class="col-sm-3 text-secondary">{{ t("Commercial Invoice") }}</dt>
						<dd class="col-sm-3 font-monospace">{{ doc.commercial_invoice || "—" }}</dd>
						<dt class="col-sm-3 text-secondary">{{ t("Supplier") }}</dt>
						<dd class="col-sm-3">{{ doc.supplier_name || doc.supplier || "—" }}</dd>
						<dt class="col-sm-3 text-secondary">{{ t("Warehouse") }}</dt>
						<dd class="col-sm-3">{{ doc.warehouse || "—" }}</dd>
						<dt class="col-sm-3 text-secondary">{{ t("Expected arrival") }}</dt>
						<dd class="col-sm-3">{{ formatDate(doc.expected_arrival_date) }}</dd>
					</dl>
				</div>
			</div>

			<!-- KPI chips -->
			<div class="row row-cards mb-3">
				<div class="col-6 col-md-3">
					<div class="card card-sm"><div class="card-body">
						<div class="text-secondary small">{{ t("Completion") }}</div>
						<div class="h3 mb-1">{{ pct(doc.completion_percentage).toFixed(0) }}%</div>
						<div class="progress" style="height: 5px">
							<div class="progress-bar" :class="progressClass(doc.completion_percentage)" :style="{ width: pct(doc.completion_percentage) + '%' }"></div>
						</div>
					</div></div>
				</div>
				<div class="col-6 col-md-3">
					<div class="card card-sm"><div class="card-body">
						<div class="text-secondary small">{{ t("Variance %") }}</div>
						<div class="h3 mb-1 font-monospace">{{ Number(doc.variance_percentage || 0).toFixed(2) }}%</div>
						<StatusBadge v-if="doc.variance_category" doctype="GRN Variance Category" :status="doc.variance_category" />
					</div></div>
				</div>
				<div class="col-6 col-md-3">
					<div class="card card-sm"><div class="card-body">
						<div class="text-secondary small">{{ t("Received (kg)") }}</div>
						<div class="h3 mb-0 font-monospace">{{ Number(doc.received_total_kg || 0).toFixed(0) }}</div>
						<div class="text-secondary small">{{ t("of {n}", { n: Number(doc.expected_total_kg || 0).toFixed(0) }) }}</div>
					</div></div>
				</div>
				<div class="col-6 col-md-3">
					<div class="card card-sm"><div class="card-body">
						<div class="text-secondary small">{{ t("Trucks received") }}</div>
						<div class="h3 mb-0 font-monospace">{{ doc.trucks_received_count || 0 }}</div>
						<div v-if="doc.claim_required" class="text-danger small"><i class="ti ti-flag me-1"></i>{{ t("Claim required") }}</div>
					</div></div>
				</div>
			</div>

			<!-- Items -->
			<div class="card mb-3">
				<div class="card-header"><h3 class="card-title">{{ t("Items") }}</h3></div>
				<div class="table-responsive">
					<table class="table table-vcenter card-table">
						<thead>
							<tr>
								<th>{{ t("Item") }}</th>
								<th class="text-end">{{ t("Expected (kg)") }}</th>
								<th class="text-end">{{ t("Received (kg)") }}</th>
								<th class="text-end">{{ t("Pending (kg)") }}</th>
								<th class="text-end">{{ t("Variance %") }}</th>
								<th>{{ t("Status") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="it in doc.items" :key="it.name">
								<td>{{ it.item_name || it.item_code }}</td>
								<td class="text-end font-monospace">{{ Number(it.expected_total_kg || 0).toFixed(0) }}</td>
								<td class="text-end font-monospace">{{ Number(it.received_kg || 0).toFixed(0) }}</td>
								<td class="text-end font-monospace">{{ Number(it.pending_kg || 0).toFixed(0) }}</td>
								<td class="text-end font-monospace">{{ Number(it.variance_percentage || 0).toFixed(2) }}%</td>
								<td><StatusBadge doctype="GRN Checklist Item" :status="it.status" /></td>
							</tr>
							<tr v-if="!doc.items.length"><td colspan="6" class="text-secondary text-center py-3">{{ t("No items.") }}</td></tr>
						</tbody>
					</table>
				</div>
			</div>

			<div class="row">
				<!-- Truck receipts -->
				<div class="col-lg-8">
					<div class="card mb-3">
						<div class="card-header">
							<h3 class="card-title">{{ t("Truck receipts") }}</h3>
							<div v-if="isDraft" class="card-actions">
								<button type="button" class="btn btn-outline-primary btn-sm" @click="newTruckReceipt">
									<i class="ti ti-plus me-1"></i>{{ t("New truck receipt") }}
								</button>
							</div>
						</div>
						<div class="table-responsive">
							<table class="table table-vcenter card-table table-hover">
								<thead>
									<tr>
										<th>{{ t("Receipt") }}</th>
										<th>{{ t("Truck") }}</th>
										<th class="text-nowrap">{{ t("Arrival") }}</th>
										<th class="text-end">{{ t("Boxes") }}</th>
										<th class="text-end">{{ t("Kg") }}</th>
										<th class="text-center">{{ t("QC") }}</th>
										<th>{{ t("PR") }}</th>
										<th>{{ t("Status") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="rc in doc.truck_receipts" :key="rc.name" style="cursor: pointer" @click="openTruckReceipt(rc.name)">
										<td class="font-monospace small text-primary">{{ rc.name }}</td>
										<td class="font-monospace small">{{ rc.truck_number || rc.truck }}</td>
										<td class="text-nowrap">{{ formatDate(rc.arrival_date) }}</td>
										<td class="text-end font-monospace">{{ rc.total_boxes_this_truck || 0 }}</td>
										<td class="text-end font-monospace">{{ Number(rc.total_kg_this_truck || 0).toFixed(0) }}</td>
										<td class="text-center">
											<i v-if="rc.temperature_check_passed" class="ti ti-temperature text-success" :title="t('Temperature OK')"></i>
											<i v-else class="ti ti-temperature-plus text-danger" :title="t('Temperature flagged')"></i>
										</td>
										<td class="font-monospace small">{{ rc.purchase_receipt || "—" }}</td>
										<td><StatusBadge doctype="GRN Checklist" :docstatus="rc.docstatus" /></td>
									</tr>
									<tr v-if="!doc.truck_receipts.length"><td colspan="8" class="text-secondary text-center py-3">{{ t("No truck receipts yet.") }}</td></tr>
								</tbody>
							</table>
						</div>
					</div>

					<!-- Landed cost vouchers -->
					<div class="card mb-3">
						<div class="card-header">
							<h3 class="card-title">{{ t("Landed cost vouchers") }}</h3>
							<div v-if="doc.docstatus === 1 && isManager" class="card-actions d-flex gap-2">
								<button type="button" class="btn btn-outline-primary btn-sm" @click="router.push('/imports/landed-cost/' + docName)">
									<i class="ti ti-calculator me-1"></i>{{ t("Landed cost review") }}
								</button>
								<button type="button" class="btn btn-ghost-secondary btn-sm" @click="addLcv">
									<i class="ti ti-plus me-1"></i>{{ t("Add voucher") }}
								</button>
							</div>
						</div>
						<div class="card-body">
							<div v-if="!doc.landed_cost_vouchers.length" class="text-secondary small">{{ t("No landed cost vouchers yet.") }}</div>
							<ul v-else class="list-unstyled mb-0">
								<li v-for="lc in doc.landed_cost_vouchers" :key="lc.lcv" class="d-flex justify-content-between border-bottom py-1">
									<span class="font-monospace small">{{ lc.lcv }}</span>
									<span class="text-secondary small"><StatusBadge doctype="Landed Cost Voucher" :docstatus="lc.docstatus" class="me-2" />{{ t(lc.note) }} · {{ formatDate(lc.posted_on) }}</span>
								</li>
							</ul>
						</div>
					</div>
				</div>

				<!-- Vet certificate card -->
				<div class="col-lg-4">
					<div class="card mb-3">
						<div class="card-header">
							<h3 class="card-title">{{ t("Veterinary certificate") }}</h3>
							<div class="card-actions">
								<span v-if="validVetCert" class="badge bg-green-lt">{{ t("Valid") }}</span>
								<span v-else class="badge bg-red-lt">{{ t("Missing") }}</span>
							</div>
						</div>
						<div class="card-body">
							<div v-if="!doc.vet_certificates.length" class="text-secondary small mb-2">{{ t("No veterinary certificate on file for this shipment.") }}</div>
							<div v-for="cert in doc.vet_certificates" :key="cert.name" class="border-bottom pb-2 mb-2">
								<div class="d-flex justify-content-between align-items-center">
									<span class="font-monospace small">{{ cert.certificate_number }}</span>
									<StatusBadge doctype="Vet Certificate" :status="cert.status" />
								</div>
								<div class="text-secondary small">{{ t("Expires") }}: {{ formatDate(cert.expiry_date) }}</div>
								<div v-if="isManager && cert.status === 'Pending'" class="d-flex gap-1 mt-1">
									<button type="button" class="btn btn-sm btn-outline-success" @click="setVetStatus(cert, 'Approved')">{{ t("Approve") }}</button>
									<button type="button" class="btn btn-sm btn-outline-danger" @click="setVetStatus(cert, 'Rejected')">{{ t("Reject") }}</button>
								</div>
							</div>

							<div v-if="showVetForm" class="mt-2">
								<div class="mb-2">
									<label class="form-label small">{{ t("Certificate number") }}</label>
									<input v-model="vetForm.certificate_number" type="text" class="form-control form-control-sm" />
								</div>
								<div class="mb-2">
									<label class="form-label small">{{ t("Issuing authority") }}</label>
									<input v-model="vetForm.issuing_authority" type="text" class="form-control form-control-sm" />
								</div>
								<div class="row g-2 mb-2">
									<div class="col-6">
										<label class="form-label small">{{ t("Issue date") }}</label>
										<DateInput v-model="vetForm.issue_date" size="sm" />
									</div>
									<div class="col-6">
										<label class="form-label small">{{ t("Expiry date") }}</label>
										<DateInput v-model="vetForm.expiry_date" size="sm" />
									</div>
								</div>
								<div class="d-flex gap-2">
									<button type="button" class="btn btn-sm btn-primary" @click="saveVetCert">{{ t("Save") }}</button>
									<button type="button" class="btn btn-sm btn-ghost-secondary" @click="showVetForm = false">{{ t("Cancel") }}</button>
								</div>
							</div>
							<button v-else type="button" class="btn btn-sm btn-outline-secondary" @click="showVetForm = true">
								<i class="ti ti-plus me-1"></i>{{ t("Add certificate") }}
							</button>
						</div>
					</div>
				</div>
			</div>
		</template>
	</div>
</template>
