<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { call } from "../../api/client.js";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";

const session = useSession();
const company = computed(() => session.activeCompany);

const side = ref("sell");
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const notice = ref("");

const currency = computed(() => rows.value[0]?.currency || session.currency);

// Aging buckets by days overdue.
const BUCKETS = [
	{ key: "b1", label: "1–30", min: 1, max: 30, color: "#f59f00" },
	{ key: "b2", label: "31–60", min: 31, max: 60, color: "#e8590c" },
	{ key: "b3", label: "61–90", min: 61, max: 90, color: "#d63939" },
	{ key: "b4", label: "90+", min: 91, max: 1e9, color: "#a4133c" },
];
function bucketOf(days) {
	return BUCKETS.find((b) => days >= b.min && days <= b.max) || BUCKETS[0];
}

const summary = computed(() => {
	const out = { total: 0, contracts: new Set(), installments: rows.value.length, oldest: 0 };
	const buckets = Object.fromEntries(BUCKETS.map((b) => [b.key, { count: 0, amount: 0 }]));
	for (const r of rows.value) {
		const amt = Number(r.outstanding || 0);
		out.total += amt;
		out.contracts.add(r.contract);
		out.oldest = Math.max(out.oldest, Number(r.days_overdue || 0));
		const b = bucketOf(Number(r.days_overdue || 0));
		buckets[b.key].count += 1;
		buckets[b.key].amount += amt;
	}
	return { total: out.total, contracts: out.contracts.size, installments: out.installments, oldest: out.oldest, buckets };
});
const maxBucketAmount = computed(() => Math.max(1, ...BUCKETS.map((b) => summary.value.buckets[b.key].amount)));

async function load() {
	if (!company.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.installment.overdue_rows", { company: company.value, side: side.value });
	} catch (err) {
		error.value = err?.message || t("Failed to load overdue installments.");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

function reminderText(r) {
	return [
		`${t("Payment overdue")} — ${r.party_name || r.party}`,
		`${t("Contract")}: ${r.contract}`,
		`${t("Due date")}: ${formatDate(r.due_date)} (${r.days_overdue} ${t("days")})`,
		`${t("Outstanding")}: ${formatMoney(r.outstanding, r.currency)}`,
	].join("\n");
}
async function copyReminder(r) {
	try {
		await navigator.clipboard.writeText(reminderText(r));
		notice.value = t("Message copied.");
		setTimeout(() => (notice.value = ""), 2500);
	} catch {
		notice.value = t("Copy failed.");
	}
}
function openExternal(url) {
	window.open(url, "_blank", "noopener");
}
function shareTelegram(r) {
	openExternal(`https://t.me/share/url?url=${encodeURIComponent(" ")}&text=${encodeURIComponent(reminderText(r))}`);
}
function shareWhatsApp(r) {
	const phone = (r.party_mobile || "").replace(/[^0-9]/g, "");
	const base = phone ? `https://wa.me/${phone}` : "https://wa.me/";
	openExternal(`${base}?text=${encodeURIComponent(reminderText(r))}`);
}

watch([company, side], load);
onMounted(load);
</script>

<template>
	<div class="card mb-3">
		<div class="card-body d-flex align-items-center gap-3 flex-wrap py-2">
			<div class="btn-group" role="group">
				<input id="od-sell" v-model="side" type="radio" class="btn-check" value="sell" />
				<label class="btn btn-outline-primary btn-sm" for="od-sell">{{ t("Sell") }}</label>
				<input id="od-buy" v-model="side" type="radio" class="btn-check" value="buy" />
				<label class="btn btn-outline-primary btn-sm" for="od-buy">{{ t("Buy") }}</label>
			</div>
			<div v-if="notice" class="small text-success"><i class="ti ti-check me-1"></i>{{ notice }}</div>
			<button type="button" class="btn btn-outline-secondary btn-sm ms-auto" :disabled="loading" @click="load">
				<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
			</button>
		</div>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>
	<div v-else-if="loading" class="text-center py-5"><div class="spinner-border text-primary"></div></div>

	<template v-else>
		<!-- Summary -->
		<div class="row row-cards g-2 mb-3">
			<div class="col-6 col-lg-3">
				<div class="card"><div class="card-body py-2">
					<div class="text-secondary small">{{ t("Total overdue") }}</div>
					<div class="h2 m-0 text-danger font-monospace">{{ formatMoney(summary.total, currency) }}</div>
				</div></div>
			</div>
			<div class="col-6 col-lg-3">
				<div class="card"><div class="card-body py-2">
					<div class="text-secondary small">{{ t("Contracts") }}</div>
					<div class="h2 m-0">{{ summary.contracts }}</div>
				</div></div>
			</div>
			<div class="col-6 col-lg-3">
				<div class="card"><div class="card-body py-2">
					<div class="text-secondary small">{{ t("Installments") }}</div>
					<div class="h2 m-0">{{ summary.installments }}</div>
				</div></div>
			</div>
			<div class="col-6 col-lg-3">
				<div class="card"><div class="card-body py-2">
					<div class="text-secondary small">{{ t("Oldest (days)") }}</div>
					<div class="h2 m-0">{{ summary.oldest }}</div>
				</div></div>
			</div>
		</div>

		<!-- Aging -->
		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title m-0">{{ t("Aging") }}</h3></div>
			<div class="card-body">
				<div v-for="b in BUCKETS" :key="b.key" class="d-flex align-items-center gap-2 mb-2">
					<div class="small" style="width: 64px;">
						<span class="badge" :style="{ background: b.color, color: '#fff' }">{{ b.label }}</span>
					</div>
					<div class="text-secondary small" style="width: 80px;">{{ summary.buckets[b.key].count }} {{ t("inst.") }}</div>
					<div class="flex-fill bg-secondary-lt rounded" style="height: 18px; overflow: hidden;">
						<div :style="{ width: (summary.buckets[b.key].amount / maxBucketAmount * 100) + '%', height: '100%', background: b.color }"></div>
					</div>
					<div class="font-monospace small fw-semibold text-end" style="width: 130px;">{{ formatMoney(summary.buckets[b.key].amount, currency) }}</div>
				</div>
			</div>
		</div>

		<!-- Table -->
		<div class="card">
			<div class="card-header"><h3 class="card-title m-0">{{ t("Overdue installments") }}</h3></div>
			<div class="table-responsive">
				<table class="table table-vcenter card-table">
					<thead>
						<tr>
							<th>{{ side === "sell" ? t("Customer") : t("Supplier") }}</th>
							<th>{{ t("Contract") }}</th>
							<th>{{ t("Due date") }}</th>
							<th class="text-end">{{ t("Outstanding") }}</th>
							<th class="text-end">{{ t("Days") }}</th>
							<th class="text-end">{{ t("Remind") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(r, i) in rows" :key="i">
							<td class="fw-semibold">{{ r.party_name || r.party }}</td>
							<td class="font-monospace small">{{ r.contract }}</td>
							<td>{{ formatDate(r.due_date) }}</td>
							<td class="text-end font-monospace">{{ formatMoney(r.outstanding, r.currency) }}</td>
							<td class="text-end">
								<span class="badge" :style="{ background: bucketOf(Number(r.days_overdue)).color, color: '#fff' }">{{ r.days_overdue }}</span>
							</td>
							<td class="text-nowrap text-end">
								<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('Telegram')" @click="shareTelegram(r)">
									<i class="ti ti-brand-telegram"></i>
								</button>
								<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('WhatsApp')" @click="shareWhatsApp(r)">
									<i class="ti ti-brand-whatsapp"></i>
								</button>
								<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('Copy reminder')" @click="copyReminder(r)">
									<i class="ti ti-copy"></i>
								</button>
							</td>
						</tr>
						<tr v-if="!rows.length">
							<td colspan="6" class="text-center text-secondary py-4">
								<i class="ti ti-circle-check d-block mb-2" style="font-size: 1.5rem; color: #2fb344;"></i>{{ t("No overdue installments.") }}
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>
	</template>
</template>
