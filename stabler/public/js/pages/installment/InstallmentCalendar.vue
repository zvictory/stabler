<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { call } from "../../api/client.js";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import CalendarMonth from "../../components/CalendarMonth.vue";

const session = useSession();
const company = computed(() => session.activeCompany);
const language = computed(() => session.user?.language || "en");

// Current month in "yyyy-mm" format — numeric construction, TZ-safe
function currentMonthKey() {
	const now = new Date();
	const y = now.getFullYear();
	const m = String(now.getMonth() + 1).padStart(2, "0");
	return `${y}-${m}`;
}

const month = ref(currentMonthKey());
const side = ref("sell");

const loading = ref(false);
const error = ref("");
const events = ref([]);

const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);
const detailError = ref("");

const currency = computed(() => {
	if (!events.value.length) return session.currency;
	return events.value[0]?.currency || session.currency;
});

async function load() {
	if (!company.value) return;
	loading.value = true;
	error.value = "";
	try {
		events.value = await call("stabler.api.installment.calendar_events", {
			company: company.value,
			side: side.value,
			month: month.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load calendar.");
	} finally {
		loading.value = false;
	}
}

async function openDetail(ev) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	detailError.value = "";
	try {
		detail.value = await call("stabler.api.installment.contract_detail", {
			name: ev.contractId,
			side: side.value,
		});
		detail.value._clickedDate = ev.date;
	} catch (err) {
		detailError.value = err?.message || t("Failed to load contract.");
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

watch([month, side], load);
onMounted(load);

const docstatusLabel = (s) =>
	s === 0 ? t("Draft") : s === 1 ? t("Submitted") : t("Cancelled");
const docstatusClass = (s) =>
	s === 0 ? "bg-yellow-lt" : s === 1 ? "bg-green-lt" : "bg-red-lt";
</script>

<template>
	<div>
		<!-- Controls bar -->
		<div class="d-flex align-items-center gap-3 mb-3 flex-wrap">
			<div class="btn-group" role="group">
				<input id="cal-sell" v-model="side" type="radio" class="btn-check" value="sell" />
				<label class="btn btn-outline-primary btn-sm" for="cal-sell">{{ t("Sell") }}</label>
				<input id="cal-buy" v-model="side" type="radio" class="btn-check" value="buy" />
				<label class="btn btn-outline-primary btn-sm" for="cal-buy">{{ t("Buy") }}</label>
			</div>
			<div class="text-secondary small ms-auto">
				{{ t("Click an installment chip to view the contract.") }}
			</div>
		</div>

		<div v-if="loading" class="text-center py-5">
			<div class="spinner-border text-primary" role="status"></div>
		</div>
		<div v-else-if="error" class="alert alert-danger">{{ error }}</div>
		<div v-else class="card">
			<div class="card-body p-2">
				<CalendarMonth
					:month="month"
					:events="events"
					:currency="currency"
					:language="language"
					@update:month="(m) => (month = m)"
					@select="openDetail"
				/>
			</div>
		</div>
	</div>

	<!-- Contract detail offcanvas (opened from chip click) -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		v-if="detailOpen"
		class="offcanvas offcanvas-end show"
		tabindex="-1"
		style="visibility: visible; width: 560px"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<i class="ti ti-file-invoice me-1"></i>{{ t("Contract") }}
			</h5>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detailError" class="alert alert-danger">{{ detailError }}</div>
			<div v-else-if="detail">
				<dl class="row mb-3">
					<dt class="col-5 text-secondary">{{ t("Contract") }}</dt>
					<dd class="col-7">{{ detail.name }}</dd>
					<dt class="col-5 text-secondary">{{ detail.side === "sell" ? t("Customer") : t("Supplier") }}</dt>
					<dd class="col-7">{{ detail.party }}</dd>
					<dt class="col-5 text-secondary">{{ t("Total") }}</dt>
					<dd class="col-7 font-monospace fw-semibold">
						{{ formatMoney(detail.grand_total, detail.currency) }}
					</dd>
					<dt class="col-5 text-secondary">{{ t("Outstanding") }}</dt>
					<dd class="col-7 font-monospace">
						{{ formatMoney(detail.outstanding_amount, detail.currency) }}
					</dd>
					<dt class="col-5 text-secondary">{{ t("Status") }}</dt>
					<dd class="col-7">
						<span class="badge" :class="docstatusClass(detail.docstatus)">
							{{ docstatusLabel(detail.docstatus) }}
						</span>
					</dd>
				</dl>

				<div class="fw-semibold small mb-2">{{ t("Payment schedule") }}</div>
				<div style="max-height: 400px; overflow: auto">
					<table class="table table-sm table-vcenter table-no-stripe">
						<thead>
							<tr>
								<th>{{ t("Due date") }}</th>
								<th>{{ t("Description") }}</th>
								<th class="text-end">{{ t("Amount") }}</th>
								<th class="text-end">{{ t("Outstanding") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr
								v-for="row in detail.payment_schedule"
								:key="row.due_date"
								:class="{ 'table-active': row.due_date === detail._clickedDate }"
							>
								<td>{{ formatDate(row.due_date) }}</td>
								<td class="text-secondary small">{{ row.description }}</td>
								<td class="text-end font-monospace">
									{{ formatMoney(row.payment_amount, detail.currency) }}
								</td>
								<td class="text-end font-monospace">
									{{ formatMoney(row.outstanding, detail.currency) }}
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</div>
	</div>
</template>
