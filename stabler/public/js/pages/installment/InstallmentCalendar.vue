<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { call } from "../../api/client.js";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import CalendarMonth from "../../components/CalendarMonth.vue";
import StatusBadge from "../../components/StatusBadge.vue";

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

// ── Share an installment with the customer ───────────────────────────────────
const shareNotice = ref("");
function buildMessage(row) {
	const d = detail.value;
	const lines = [
		`${t("Payment reminder")} — ${d.party_name || d.party}`,
		`${t("Contract")}: ${d.name}`,
		`${t("Due date")}: ${formatDate(row.due_date)}`,
		`${t("Amount")}: ${formatMoney(row.payment_amount, d.currency)}`,
	];
	if (Number(row.outstanding) > 0) {
		lines.push(`${t("Outstanding")}: ${formatMoney(row.outstanding, d.currency)}`);
	}
	return lines.join("\n");
}
function openExternal(url) {
	window.open(url, "_blank", "noopener");
}
function shareTelegram(row) {
	openExternal(`https://t.me/share/url?url=${encodeURIComponent(" ")}&text=${encodeURIComponent(buildMessage(row))}`);
}
function shareWhatsApp(row) {
	const phone = (detail.value.party_mobile || "").replace(/[^0-9]/g, "");
	const base = phone ? `https://wa.me/${phone}` : "https://wa.me/";
	openExternal(`${base}?text=${encodeURIComponent(buildMessage(row))}`);
}
async function copyMessage(row) {
	try {
		await navigator.clipboard.writeText(buildMessage(row));
		shareNotice.value = t("Message copied.");
		setTimeout(() => (shareNotice.value = ""), 2500);
	} catch {
		shareNotice.value = t("Copy failed.");
	}
}
function nextDayCompact(yyyymmdd) {
	const y = +yyyymmdd.slice(0, 4), m = +yyyymmdd.slice(4, 6), d = +yyyymmdd.slice(6, 8);
	const dt = new Date(y, m - 1, d + 1);
	const p = (n) => String(n).padStart(2, "0");
	return `${dt.getFullYear()}${p(dt.getMonth() + 1)}${p(dt.getDate())}`;
}
function gcalUrl(row) {
	const d = detail.value;
	const start = row.due_date.replaceAll("-", "");
	const text = `${t("Installment")} — ${d.party_name || d.party}`;
	return `https://calendar.google.com/calendar/render?action=TEMPLATE&text=${encodeURIComponent(text)}&dates=${start}/${nextDayCompact(start)}&details=${encodeURIComponent(buildMessage(row))}`;
}
function addToGoogle(row) {
	openExternal(gcalUrl(row));
}
function downloadIcs(row) {
	const d = detail.value;
	const start = row.due_date.replaceAll("-", "");
	const esc = (s) => String(s).replace(/[\\,;]/g, (m) => "\\" + m).replaceAll("\n", "\\n");
	const ics = [
		"BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Stabler//Installment//EN",
		"BEGIN:VEVENT", `UID:${d.name}-${row.due_date}@stabler`,
		`DTSTART;VALUE=DATE:${start}`, `DTEND;VALUE=DATE:${nextDayCompact(start)}`,
		`SUMMARY:${esc(t("Installment") + " — " + (d.party_name || d.party))}`,
		`DESCRIPTION:${esc(buildMessage(row))}`,
		"END:VEVENT", "END:VCALENDAR",
	].join("\r\n");
	const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
	const a = document.createElement("a");
	a.href = URL.createObjectURL(blob);
	a.download = `${d.name}-${row.due_date}.ics`;
	a.click();
	URL.revokeObjectURL(a.href);
}

watch([month, side], load);
onMounted(load);
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
						<StatusBadge doctype="Sales Invoice" :docstatus="detail.docstatus" />
					</dd>
				</dl>

				<div class="d-flex align-items-center mb-2">
					<div class="fw-semibold small">{{ t("Payment schedule") }}</div>
					<div v-if="shareNotice" class="ms-auto small text-success"><i class="ti ti-check me-1"></i>{{ shareNotice }}</div>
				</div>
				<div style="max-height: 400px; overflow: auto">
					<table class="table table-sm table-vcenter table-no-stripe">
						<thead>
							<tr>
								<th>{{ t("Due date") }}</th>
								<th class="text-end">{{ t("Amount") }}</th>
								<th class="text-end">{{ t("Outstanding") }}</th>
								<th class="text-end">{{ t("Share") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr
								v-for="row in detail.payment_schedule"
								:key="row.due_date"
								:class="{ 'table-active': row.due_date === detail._clickedDate }"
							>
								<td>
									{{ formatDate(row.due_date) }}
									<div v-if="row.description" class="text-secondary" style="font-size:.72rem">{{ row.description }}</div>
								</td>
								<td class="text-end font-monospace">
									{{ formatMoney(row.payment_amount, detail.currency) }}
								</td>
								<td class="text-end font-monospace">
									{{ formatMoney(row.outstanding, detail.currency) }}
								</td>
								<td class="text-nowrap text-end">
									<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('Telegram')" @click="shareTelegram(row)"><i class="ti ti-brand-telegram"></i></button>
									<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('WhatsApp')" @click="shareWhatsApp(row)"><i class="ti ti-brand-whatsapp"></i></button>
									<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('Copy message')" @click="copyMessage(row)"><i class="ti ti-copy"></i></button>
									<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('Add to Google Calendar')" @click="addToGoogle(row)"><i class="ti ti-calendar-plus"></i></button>
									<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('Download .ics')" @click="downloadIcs(row)"><i class="ti ti-download"></i></button>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</div>
	</div>
</template>
