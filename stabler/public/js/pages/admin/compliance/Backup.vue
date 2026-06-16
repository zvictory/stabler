<script setup>
// Backup & disaster-recovery control surface (System Manager only).
// Local backups, retention, off-box copy to Google Drive, restore-test tracker.
import { computed, onMounted, ref } from "vue";
import { call } from "../../../api/client.js";
import { formatDateTime } from "../../../composables/date.js";
import { t } from "../../../composables/i18n.js";
import { useToast } from "../../../composables/useToast.js";
import { useConfirm } from "../../../composables/useConfirm.js";
import SkeletonRows from "../../../components/SkeletonRows.vue";

const toast = useToast();
const { confirm } = useConfirm();

const loading = ref(false);
const busy = ref("");
const status = ref(null);
const drive = ref(null);
const backups = ref([]);

async function loadAll() {
	loading.value = true;
	try {
		const [st, dr, bk] = await Promise.all([
			call("stabler.api.backup.backup_status"),
			call("stabler.api.backup.gdrive_status"),
			call("stabler.api.backup.list_backups"),
		]);
		status.value = st;
		drive.value = dr;
		backups.value = bk.sets || [];
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		loading.value = false;
	}
}

async function backupNow(withFiles) {
	busy.value = "backup";
	try {
		await call("stabler.api.backup.create_backup", { with_files: withFiles ? 1 : 0 });
		toast.success(t("Backup created."));
		await loadAll();
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = "";
	}
}

async function uploadToDrive() {
	busy.value = "drive";
	try {
		const r = await call("stabler.api.backup.upload_latest_to_drive");
		toast.success(t("Uploaded {0} file(s) to Google Drive.").replace("{0}", r.count));
		await loadAll();
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = "";
	}
}

async function markRestoreTested() {
	const ok = await confirm({
		title: t("Confirm restore test"),
		body: t("Only confirm after you have actually restored a backup to a scratch site and verified the data. This records today as the last successful restore test."),
		confirmLabel: t("I have tested a restore"),
	});
	if (!ok) return;
	busy.value = "restore";
	try {
		await call("stabler.api.backup.mark_restore_tested");
		toast.success(t("Restore test recorded."));
		await loadAll();
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = "";
	}
}

const lastBackupLabel = computed(() =>
	status.value?.last_backup_at ? formatDateTime(status.value.last_backup_at) : t("Never"),
);
const driveReady = computed(() => drive.value?.ready);

onMounted(loadAll);
</script>

<template>
	<div>
		<div v-if="loading && !status" class="text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>

		<template v-else>
			<!-- Status cards -->
			<div class="row row-cards mb-3">
				<div class="col-sm-6 col-lg-3">
					<div class="card card-sm">
						<div class="card-body">
							<div class="text-secondary small">{{ t("Last backup") }}</div>
							<div class="h3 mb-0">{{ lastBackupLabel }}</div>
							<div class="text-secondary small">
								{{ status?.set_count || 0 }} {{ t("sets") }} · {{ status?.total_size_label }}
							</div>
						</div>
					</div>
				</div>
				<div class="col-sm-6 col-lg-3">
					<div class="card card-sm">
						<div class="card-body">
							<div class="text-secondary small">{{ t("Off-box (Google Drive)") }}</div>
							<div class="h3 mb-0">
								<span v-if="driveReady" class="text-green">{{ t("Ready") }}</span>
								<span v-else-if="status?.config?.to_drive" class="text-yellow">{{ t("Needs setup") }}</span>
								<span v-else class="text-secondary">{{ t("Off") }}</span>
							</div>
							<div class="text-secondary small">
								{{ drive?.last_upload_at ? formatDateTime(drive.last_upload_at) : t("Not uploaded yet") }}
							</div>
						</div>
					</div>
				</div>
				<div class="col-sm-6 col-lg-3">
					<div class="card card-sm" :class="status?.restore_test_overdue ? 'bg-red-lt' : ''">
						<div class="card-body">
							<div class="text-secondary small">{{ t("Restore test") }}</div>
							<div class="h3 mb-0">
								<span v-if="status?.restore_test_overdue" class="text-red">{{ t("Overdue") }}</span>
								<span v-else class="text-green">{{ t("OK") }}</span>
							</div>
							<div class="text-secondary small">
								{{ status?.last_restore_test ? status.last_restore_test : t("Never tested") }}
							</div>
						</div>
					</div>
				</div>
				<div class="col-sm-6 col-lg-3">
					<div class="card card-sm">
						<div class="card-body">
							<div class="text-secondary small">{{ t("Daily auto-backup") }}</div>
							<div class="h3 mb-0">
								<span v-if="status?.config?.enabled" class="text-green">{{ t("On") }}</span>
								<span v-else class="text-secondary">{{ t("Off") }}</span>
							</div>
							<div class="text-secondary small">
								{{ t("Keep") }} {{ status?.config?.retention_days }} {{ t("days") }}
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- Restore-overdue banner -->
			<div v-if="status?.restore_test_overdue" class="alert alert-warning d-flex align-items-center">
				<i class="ti ti-alert-triangle me-2"></i>
				<div>
					{{ t("No verified restore on record. A backup you have never restored is not a backup you can trust — test one and record it.") }}
				</div>
			</div>

			<!-- Actions -->
			<div class="btn-list mb-3">
				<button class="btn btn-primary" :disabled="busy === 'backup'" @click="backupNow(false)">
					<i class="ti ti-database-export me-1"></i>{{ t("Back up now") }}
				</button>
				<button class="btn btn-outline-secondary" :disabled="busy === 'backup'" @click="backupNow(true)">
					{{ t("Back up with files") }}
				</button>
				<button
					class="btn btn-outline-secondary"
					:disabled="busy === 'drive' || !driveReady"
					:title="driveReady ? '' : t('Configure Google Drive below first.')"
					@click="uploadToDrive"
				>
					<i class="ti ti-brand-google-drive me-1"></i>{{ t("Upload latest to Drive") }}
				</button>
				<button class="btn btn-ghost-secondary ms-auto" :disabled="busy === 'restore'" @click="markRestoreTested">
					<i class="ti ti-check me-1"></i>{{ t("Mark restore tested") }}
				</button>
			</div>

			<!-- Google Drive setup hint -->
			<div v-if="status?.config?.to_drive && !driveReady" class="alert alert-info">
				<div class="fw-medium mb-1">{{ t("Finish Google Drive setup") }}</div>
				<ul class="mb-0 small">
					<li v-if="!drive?.libraries_installed">
						{{ t("Install libraries on the server:") }}
						<code>pip install google-api-python-client google-auth</code>
					</li>
					<li v-if="!drive?.service_account_configured">
						{{ t("Add a service account to site_config.json key") }}
						<code>stabler_gdrive_service_account</code>
						{{ t("(path to the JSON, or the JSON inline).") }}
					</li>
					<li v-if="!status?.config?.folder_id">
						{{ t("Set the Google Drive folder ID in Stabler Settings, and share that Shared-Drive folder with the service account email.") }}
						<span v-if="drive?.service_account_email" class="font-monospace">{{ drive.service_account_email }}</span>
					</li>
				</ul>
			</div>

			<!-- Backup list -->
			<div class="table-responsive">
				<table class="table card-table table-vcenter">
					<thead>
						<tr>
							<th>{{ t("Backup set") }}</th>
							<th>{{ t("Contents") }}</th>
							<th class="text-end">{{ t("Size") }}</th>
							<th>{{ t("Created") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :rows="4" :cols="4" />
					<tbody v-else>
						<tr v-for="s in backups" :key="s.key">
							<td class="font-monospace">{{ s.key }}</td>
							<td>
								<span v-if="s.has_database" class="badge bg-green-lt me-1">{{ t("Database") }}</span>
								<span v-if="s.has_files" class="badge bg-blue-lt">{{ t("Files") }}</span>
							</td>
							<td class="text-end font-monospace">{{ s.size_label }}</td>
							<td class="text-secondary small">{{ formatDateTime(s.modified) }}</td>
						</tr>
						<tr v-if="backups.length === 0">
							<td colspan="4" class="text-center text-secondary py-4">
								{{ t("No backups on disk yet. Click “Back up now”.") }}
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</template>
	</div>
</template>
