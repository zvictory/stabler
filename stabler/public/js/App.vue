<script setup>
import Sidebar from "./components/Sidebar.vue";
import CommandPalette from "./components/CommandPalette.vue";
</script>

<template>
	<div class="page">
		<Sidebar />
		<div class="page-wrapper">
			<router-view v-slot="{ Component }">
				<component :is="Component" />
			</router-view>

			<CommandPalette />

			<footer class="footer footer-transparent d-print-none">
				<div class="container-xl">
					<div class="row text-center align-items-center flex-row-reverse">
						<div class="col-lg-auto ms-lg-auto">
							<ul class="list-inline list-inline-dots mb-0">
								<li class="list-inline-item">Stabler v0.1</li>
							</ul>
						</div>
						<div class="col-12 col-lg-auto mt-3 mt-lg-0">
							<ul class="list-inline list-inline-dots mb-0">
								<li class="list-inline-item">© 2026 Stabler</li>
							</ul>
						</div>
					</div>
				</div>
			</footer>
		</div>
	</div>
</template>
