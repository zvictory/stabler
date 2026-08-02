<script setup>
/* Route-addressable Deal 360 Full Workspace View (/crm/deals/:name).
 *
 * Provides a 360° overview of a CRM Deal: owner, stage progress,
 * contract value, deadline, activities, email composition, and finance snapshot.
 */
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";

const route = useRoute();
const session = useSession();
const { activeCompany } = storeToRefs(session);
const toast = useToast();

const dealName = computed(() => String(route.params.name || route.query.deal || ""));
const deal = ref(null);
const loading = ref(false);

const emailSubject = ref("");
const emailContent = ref("");
const emailSending = ref(false);

async function loadDeal() {
	if (!dealName.value) return;
	loading.value = true;
	try {
		const res = await call("stabler.api.crm.get_deal", {
			name: dealName.value,
			company: activeCompany.value,
		});
		deal.value = res;
	} catch (err) {
		toast.error(err?.message || t("Could not load deal."));
	} finally {
		loading.value = false;
	}
}

async function sendEmail() {
	if (!emailSubject.value || !emailContent.value || emailSending.value) return;
	emailSending.value = true;
	try {
		await call("stabler.api.crm_email.send_deal_email", {
			deal: dealName.value,
			subject: emailSubject.value,
			content: emailContent.value,
			company: activeCompany.value,
		});
		toast.success(t("Email sent."));
		emailSubject.value = "";
		emailContent.value = "";
	} catch (err) {
		toast.error(err?.message || t("Failed to send email."));
	} finally {
		emailSending.value = false;
	}
}

onMounted(() => {
	loadDeal();
});
</script>

<template>
	<div class="deal-360 container-xl py-3">
		<header class="d-flex justify-content-between align-items-center mb-3">
			<div>
				<router-link to="/crm/deals" class="btn btn-outline-secondary btn-sm me-2">
					<i class="ti ti-arrow-left me-1"></i>{{ t("Back to Deals") }}
				</router-link>
				<h2 class="d-inline-block align-middle mb-0">
					{{ deal?.organization || deal?.name || dealName }}
				</h2>
			</div>
			<div class="d-flex align-items-center gap-2">
				<span class="badge bg-primary-lt text-primary text-capitalize">{{ deal?.stage || "—" }}</span>
			</div>
		</header>

		<div v-if="loading" class="text-center py-5">
			<div class="spinner-border text-primary" role="status"></div>
		</div>

		<div v-else-if="deal" class="row g-3">
			<div class="col-md-8">
				<div class="card mb-3">
					<div class="card-header py-2 fw-semibold">{{ t("Deal Details") }}</div>
					<div class="card-body">
						<div class="row g-3 mb-3">
							<div class="col-md-6">
								<label class="form-label small text-secondary">{{ t("Contract Value") }}</label>
								<MoneyInput v-model="deal.contract_value" size="sm" readonly />
							</div>
							<div class="col-md-6">
								<label class="form-label small text-secondary">{{ t("Deadline") }}</label>
								<DateInput v-model="deal.deadline" size="sm" readonly />
							</div>
						</div>
					</div>
				</div>

				<!-- Email Composer -->
				<div class="card">
					<div class="card-header py-2 fw-semibold d-flex align-items-center gap-2">
						<i class="ti ti-mail text-primary"></i>
						<span>{{ t("Send Email Communication") }}</span>
					</div>
					<div class="card-body">
						<div class="mb-2">
							<label class="form-label small">{{ t("Subject") }}</label>
							<input
								v-model="emailSubject"
								type="text"
								class="form-control form-control-sm"
								:placeholder="t('Enter email subject…')"
							/>
						</div>
						<div class="mb-3">
							<label class="form-label small">{{ t("Message") }}</label>
							<textarea
								v-model="emailContent"
								class="form-control form-control-sm"
								rows="3"
								:placeholder="t('Write email body…')"
							></textarea>
						</div>
						<button
							type="button"
							class="btn btn-primary btn-sm"
							:disabled="emailSending || !emailSubject || !emailContent"
							@click="sendEmail"
						>
							<span v-if="emailSending" class="spinner-border spinner-border-sm me-1"></span>
							{{ t("Send Email") }}
						</button>
					</div>
				</div>
			</div>

			<div class="col-md-4">
				<div class="card">
					<div class="card-header py-2 fw-semibold">{{ t("Tender & Finance Snapshot") }}</div>
					<div class="card-body p-0">
						<ul class="list-group list-group-flush">
							<li class="list-group-item d-flex justify-content-between align-items-center">
								<span>{{ t("Parent Tender") }}</span>
								<span class="font-monospace fw-semibold">{{ deal.custom_parent_tender || "—" }}</span>
							</li>
							<li class="list-group-item d-flex justify-content-between align-items-center">
								<span>{{ t("Owner") }}</span>
								<span>{{ deal.owner || "—" }}</span>
							</li>
						</ul>
					</div>
				</div>
			</div>
		</div>

		<EmptyState
			v-else
			icon="ti-alert-circle"
			:title="t('Deal not found.')"
			:subtitle="t('The requested deal could not be loaded for this company.')"
		/>
	</div>
</template>
