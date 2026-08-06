<script setup>
/**
 * FileSlot — single document-requirement attachment control.
 *
 * One dropzone per document requirement (ГТД, CMR, invoice…). Uploads the
 * picked/dropped file straight to Frappe's stock `/api/method/upload_file`,
 * attaching it to the given doctype/name as a private File (tender documents
 * carry price + customer data), then emits the resulting file meta so the
 * parent can persist it via the tender document endpoint.
 *
 * The component owns only the upload UX + progress. The parent decides where
 * the returned {file_url, file_name, file_size} lands (intake JSON / Tender
 * Master / download endpoint). Reuses the upload contract proven in
 * sfa/Photos.vue (CSRF token from window.__STABLER__, FormData → upload_file).
 *
 * Props:
 *   attachedTo     — doctype the File attaches to ("CRM Deal" | "Tender Master")
 *   attachedName   — name of that doctype
 *   accept         — input accept hint (default: broad)
 *   disabled       — read-only (no upload / no remove)
 *   compact        — tighter rendering for table cells
 *   existing       — current latest_file object {file_name, file_url, ...} | null
 *
 * Emits:
 *   uploaded(file) — {file_name, file_url, file_size} after a successful upload
 *   remove()       — user asked to detach the current file (parent confirms)
 */
import { computed, ref } from "vue";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";

const props = defineProps({
	attachedTo: { type: String, default: "CRM Deal" },
	attachedName: { type: String, default: "" },
	accept: { type: String, default: "" },
	disabled: { type: Boolean, default: false },
	compact: { type: Boolean, default: false },
	existing: { type: Object, default: null },
	downloadEndpoint: { type: String, default: "" },
	downloadParams: { type: Object, default: () => ({}) },
});

const emit = defineEmits(["uploaded", "remove"]);

const toast = useToast();
const inputRef = ref(null);
const dragging = ref(false);
const uploading = ref(false);

const current = computed(() => props.existing || null);

function humanSize(bytes) {
	const b = Number(bytes) || 0;
	if (!b) return "";
	const units = ["B", "KB", "MB", "GB"];
	let i = 0;
	let n = b;
	while (n >= 1024 && i < units.length - 1) {
		n /= 1024;
		i++;
	}
	return `${n >= 100 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

function isImage(url) {
	return /\.(png|jpe?g|gif|webp|svg)$/i.test(url || "");
}

// Optional gated download: when a backend endpoint (e.g. download_tender_document)
// is supplied, route the click through it so company scope + requirement ownership
// are enforced server-side. Falls back to a direct link when not supplied (Frappe's
// session cookie already authorizes /private/files/ for a logged-in browser).
async function download() {
	const cur = current.value;
	if (!cur || !cur.file_url) return;
	if (!props.downloadEndpoint) {
		window.open(cur.file_url, "_blank", "noopener");
		return;
	}
	try {
		// The gated endpoint returns a redirect to the file URL; open it directly so
		// the browser handles the redirect + content disposition.
		const params = new URLSearchParams({ ...props.downloadParams, file_url: cur.file_url });
		window.open(`/api/method/${props.downloadEndpoint}?${params}`, "_blank", "noopener");
	} catch (e) {
		toast.error(e?.message || t("Download failed"));
	}
}

function trigger() {
	if (props.disabled || uploading.value) return;
	inputRef.value?.click();
}

function onPick(e) {
	const file = e.target.files?.[0];
	if (file) upload(file);
	// allow re-picking the same file
	e.target.value = "";
}

function onDrop(e) {
	dragging.value = false;
	if (props.disabled || uploading.value) return;
	const file = e.dataTransfer?.files?.[0];
	if (file) upload(file);
}

function onPaste(e) {
	if (props.disabled || uploading.value) return;
	const file = e.clipboardData?.files?.[0];
	if (file) upload(file);
}

async function upload(file) {
	uploading.value = true;
	try {
		const fd = new FormData();
		fd.append("file", file);
		fd.append("is_private", "1");
		if (props.attachedTo && props.attachedName) {
			fd.append("doctype", props.attachedTo);
			fd.append("docname", props.attachedName);
		}
		const csrf = (window.__STABLER__ && window.__STABLER__.csrfToken) || "";
		const res = await fetch("/api/method/upload_file", {
			method: "POST",
			credentials: "same-origin",
			body: fd,
			headers: { "X-Frappe-CSRF-Token": csrf },
		});
		if (!res.ok) throw new Error(`${t("Upload failed")}: ${res.status}`);
		const json = await res.json();
		const msg = json.message || {};
		if (!msg.file_url) throw new Error(t("Upload returned no file URL."));
		emit("uploaded", {
			file_name: msg.file_name || file.name,
			file_url: msg.file_url,
			file_size: Number(msg.file_size) || file.size || 0,
		});
	} catch (err) {
		toast.error(err?.message || t("Upload failed"));
	} finally {
		uploading.value = false;
	}
}

defineExpose({ uploading });
</script>

<template>
	<div
		class="fs-slot"
		:class="{ 'fs-slot-compact': compact, 'fs-dragging': dragging, 'fs-disabled': disabled, 'fs-filled': current }"
		@dragover.prevent="dragging = !disabled"
		@dragleave.prevent="dragging = false"
		@drop.prevent="onDrop"
		@paste="onPaste"
	>
		<input
			ref="inputRef"
			type="file"
			class="d-none"
			:accept="accept"
			:disabled="disabled || uploading"
			@change="onPick"
		/>

		<!-- Filled state: show the attached file chip -->
		<div v-if="current" class="fs-chip">
			<i class="ti fs-chip-ic" :class="isImage(current.file_url) ? 'ti-photo' : 'ti-file-text'"></i>
			<a v-if="current.file_url" href="#" class="fs-chip-name text-truncate" :title="current.file_name" @click.prevent="download">
				{{ current.file_name || current.file_url }}
			</a>
			<span v-else class="fs-chip-name text-truncate">{{ current.file_name }}</span>
			<span class="fs-chip-size font-monospace">{{ humanSize(current.file_size) }}</span>
			<button
				v-if="!disabled"
				type="button"
				class="btn btn-ghost-danger btn-icon btn-sm fs-chip-rm"
				:title="t('Remove file')"
				@click="emit('remove')"
			><i class="ti ti-x"></i></button>
		</div>

		<!-- Empty / dropzone state -->
		<button
			v-else
			type="button"
			class="fs-drop btn btn-light w-100 text-start"
			:disabled="disabled || uploading"
			@click="trigger"
		>
			<span v-if="uploading" class="spinner-border spinner-border-sm text-secondary me-1"></span>
			<i v-else class="ti ti-paperclip me-1 text-secondary"></i>
			<span class="fs-drop-lbl">{{ uploading ? t("Uploading…") : t("Attach file") }}</span>
		</button>
	</div>
</template>

<style scoped>
.fs-slot { min-width: 160px; }
.fs-slot-compact { min-width: 130px; }
.fs-drop {
	border: 1px dashed var(--stbl-border, #dbe1ea);
	border-radius: 8px;
	padding: 4px 10px;
	font-size: 12.5px;
	color: var(--stbl-text-secondary, #6a7690);
	font-weight: 500;
}
.fs-drop:hover:not(:disabled) { border-color: var(--tblr-primary, #0054a6); color: var(--tblr-primary, #0054a6); }
.fs-dragging .fs-drop { border-color: var(--tblr-primary, #0054a6); background: var(--tblr-primary-lt, #eef4ff); }
.fs-disabled { opacity: .6; pointer-events: none; }
.fs-drop-lbl { vertical-align: middle; }

.fs-chip {
	display: flex;
	align-items: center;
	gap: 6px;
	padding: 3px 4px 3px 8px;
	border: 1px solid var(--stbl-border, #dbe1ea);
	border-radius: 8px;
	background: var(--stbl-surface, #fff);
	font-size: 12.5px;
}
.fs-chip-ic { color: var(--stbl-text-secondary, #6a7690); font-size: 14px; flex: none; }
.fs-chip-name { max-width: 180px; font-weight: 500; }
.fs-slot-compact .fs-chip-name { max-width: 120px; }
.fs-chip-size { font-size: 11px; color: var(--stbl-text-secondary, #6a7690); flex: none; }
.fs-chip-rm { flex: none; }
</style>
