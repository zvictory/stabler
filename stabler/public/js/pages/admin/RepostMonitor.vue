<script setup>
import { computed, onMounted, ref } from "vue";
import { call } from "../../api/client.js";
import { formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";

const toast = useToast();
const { confirm } = useConfirm();

const loading = ref(false);
const data = ref(null);
const busy = ref(false);

async function load() {
	loading.value = true;
	try {
		data.value = await call("stabler.api.repost_monitor.repost_status");
	} catch (err) {
		toast.error(err?.message || t("Could not load repost status."));
	} finally {
		loading.value = false;
	}
}
onMounted(load);

const counts = computed(() => data.value?.counts || {});
const inProgress = computed(() => data.value?.in_progress || []);
const errors = computed(() => data.value?.errors || []);
const stuck = computed(() => inProgress.value.filter((r) => r.stuck_minutes >= 30));

async function runNow() {
	busy.value = true;
	try {
		await call("stabler.api.repost_monitor.repost_run_now");
		toast.success(t("Repost processor queued. Refresh in a moment."));
	} catch (err) {
		toast.error(err?.message || t("Could not start the processor."));
	} finally {
		busy.value = false;
	}
}
async function resetStuck() {
	const ok = await confirm({
		title: t("Re-queue stuck reposts?"),
		body: t("Reposts stuck 'In Progress' for over 30 minutes will be set back to Queued so the processor resumes."),
		confirmLabel: t("Re-queue"),
	});
	if (!ok) return;
	busy.value = true;
	try {
		const r = await call("stabler.api.repost_monitor.repost_reset_stuck", { minutes: 30 });
		toast.success(t("Re-queued {0} reposts.").replace("{0}", r.count));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Reset failed."));
	} finally {
		busy.value = false;
	}
}

const STATUS_CLS = { Queued: "bg-yellow-lt text-yellow", "In Progress": "bg-blue-lt text-blue", Completed: "bg-green-lt text-green", Failed: "bg-red-lt text-red", Error: "bg-red-lt text-red", Skipped: "bg-secondary-lt" };
</script>

<template>
	<div class="container-xl py-3">
		<div class="d-flex align-items-center mb-3 gap-2">
			<h2 class="mb-0">{{ t("Repost queue") }}</h2>
			<button type="button" class="btn btn-outline-secondary btn-sm ms-auto" :disabled="loading" @click="load">
				<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
			</button>
			<button type="button" class="btn btn-outline-warning btn-sm" :disabled="busy || !stuck.length" @click="resetStuck">
				<i class="ti ti-restore me-1"></i>{{ t("Re-queue stuck") }}<span v-if="stuck.length"> ({{ stuck.length }})</span>
			</button>
			<button type="button" class="btn btn-primary btn-sm" :disabled="busy" @click="runNow">
				<span v-if="busy" class="spinner-border spinner-border-sm me-1"></span>
				<i v-else class="ti ti-player-play me-1"></i>{{ t("Run now") }}
			</button>
		</div>

		<div v-if="loading" class="text-center py-5"><span class="spinner-border text-primary"></span></div>
		<template v-else-if="data">
			<!-- Stuck warning -->
			<div v-if="stuck.length" class="alert alert-warning d-flex align-items-center gap-2">
				<i class="ti ti-alert-triangle"></i>
				<span>{{ t("The queue is blocked — {0} repost(s) stuck. Re-queue them, then Run now.").replace("{0}", stuck.length) }}</span>
			</div>

			<!-- Status counts -->
			<div class="row g-2 mb-3">
				<div v-for="(n, s) in counts" :key="s" class="col-auto">
					<div class="card card-sm"><div class="card-body py-2 px-3">
						<span class="badge me-2" :class="STATUS_CLS[s] || 'bg-secondary-lt'">{{ s }}</span>
						<span class="fw-bold font-monospace">{{ n }}</span>
					</div></div>
				</div>
				<div v-if="data.oldest_queued" class="col-auto">
					<div class="card card-sm"><div class="card-body py-2 px-3 text-secondary small">
						{{ t("Oldest queued") }}: {{ formatDateTime(data.oldest_queued) }}
					</div></div>
				</div>
			</div>

			<!-- In progress -->
			<div v-if="inProgress.length" class="card mb-3">
				<div class="card-header"><h4 class="card-title mb-0">{{ t("In progress") }}</h4></div>
				<div class="card-body p-0">
					<table class="table card-table">
						<thead><tr><th>{{ t("Repost") }}</th><th>{{ t("Voucher") }}</th><th class="text-end">{{ t("Stuck (min)") }}</th></tr></thead>
						<tbody>
							<tr v-for="r in inProgress" :key="r.name" :class="{ 'table-warning': r.stuck_minutes >= 30 }">
								<td class="font-monospace small">{{ r.name }}</td>
								<td class="small">{{ r.voucher_type }} · {{ r.voucher_no }}</td>
								<td class="text-end font-monospace">{{ r.stuck_minutes }}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- Errors -->
			<div v-if="errors.length" class="card">
				<div class="card-header"><h4 class="card-title mb-0 text-danger">{{ t("Errors") }} ({{ errors.length }})</h4></div>
				<div class="card-body p-0">
					<table class="table card-table">
						<thead><tr><th>{{ t("Repost") }}</th><th>{{ t("Voucher") }}</th><th>{{ t("When") }}</th></tr></thead>
						<tbody>
							<tr v-for="r in errors" :key="r.name">
								<td class="font-monospace small">{{ r.name }}</td>
								<td class="small">{{ r.voucher_type }} · {{ r.voucher_no }}</td>
								<td class="small text-secondary">{{ formatDateTime(r.modified) }}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<div v-if="!inProgress.length && !errors.length && !data.queued" class="text-center py-4 text-secondary">
				<i class="ti ti-checks ti-lg text-success d-block mb-2"></i>{{ t("Queue is clear. Nothing pending.") }}
			</div>
		</template>
	</div>
</template>
