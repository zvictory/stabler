<script setup>
import { computed, ref } from "vue";
import { orgApi } from "../api/organization.js";
import { t } from "../composables/i18n.js";
import { useSession } from "../stores/session.js";

const session = useSession();

const LANGUAGES = [
	{ code: "en", label: "English" },
	{ code: "ru", label: "Русский" },
	{ code: "uz", label: "O‘zbekcha" },
	{ code: "uzc", label: "Ўзбекча" },
	{ code: "tr", label: "Türkçe" },
];

const currentLanguage = computed(() => session.user?.language || "en");
const identity = computed(() => session.user?.name || session.user?.id || "");
const email = computed(() => session.user?.id || "");
const initial = computed(() => identity.value.trim().slice(0, 1).toUpperCase() || "U");
const error = ref("");

async function setLanguage(code) {
	if (code === currentLanguage.value) return;
	error.value = "";
	try {
		await orgApi.updateLanguage(code);
	} catch (err) {
		error.value = err?.message || t("Failed to switch language.");
		return;
	}
	window.location.reload();
}
</script>

<template>
	<div class="page-header d-print-none">
		<div class="container-xl">
			<div class="row g-2 align-items-center">
				<div class="col">
					<h2 class="page-title d-flex align-items-center gap-2">
						<i class="ti ti-user-circle"></i>{{ t("Profile") }}
					</h2>
				</div>
			</div>
		</div>
	</div>

	<div class="page-body">
		<div class="container-xl">
			<div class="row g-3">
				<div class="col-lg-4">
					<div class="card">
						<div class="card-body d-flex align-items-center gap-3">
							<span
								v-if="session.user.image"
								class="avatar avatar-xl"
								:style="{ backgroundImage: `url('${session.user.image}')` }"
							></span>
							<span v-else class="avatar avatar-xl bg-blue-lt text-blue">{{ initial }}</span>
							<div class="min-w-0">
								<div class="h3 mb-1 text-truncate">{{ identity }}</div>
								<div class="stbl-subtext text-truncate">{{ email }}</div>
								<div class="stbl-subtext text-truncate">{{ session.activeCompany || "—" }}</div>
							</div>
						</div>
					</div>
				</div>

				<div class="col-lg-8">
					<div class="card">
						<div class="card-header">
							<div class="card-title">{{ t("Language") }}</div>
						</div>
						<div v-if="error" class="alert alert-danger m-3 mb-0" role="alert">
							{{ error }}
						</div>
						<div class="list-group list-group-flush">
							<button
								v-for="lng in LANGUAGES"
								:key="lng.code"
								type="button"
								class="list-group-item list-group-item-action d-flex align-items-center justify-content-between"
								@click="setLanguage(lng.code)"
							>
								<span>{{ lng.label }}</span>
								<i v-if="lng.code === currentLanguage" class="ti ti-check text-primary"></i>
							</button>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
