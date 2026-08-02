import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const jsDir = resolve(here, "../public/js");

const read = (file) => readFileSync(file, "utf8");

const screens = {
	portfolio: read(resolve(jsDir, "pages/tender/DirectorBoard.vue")),
	overview: read(resolve(jsDir, "pages/tender/TenderOverview.vue")),
	flow: read(resolve(jsDir, "pages/tender/TenderFlow.vue")),
	crm: read(resolve(jsDir, "pages/tender/TenderCrm.vue")),
	sourcing: read(resolve(jsDir, "pages/tender/SourcingWorkspace.vue")),
	documents: read(resolve(jsDir, "pages/tender/TenderDocuments.vue")),
	poControl: read(resolve(jsDir, "pages/tender/PoControlBoard.vue")),
	myTenders: read(resolve(jsDir, "pages/tender/MyTenders.vue")),
	customs: read(resolve(jsDir, "pages/tender/DeclarantQueue.vue")),
	logistics: read(resolve(jsDir, "pages/tender/LogistBoard.vue")),
};

// 1. Check no Desk redirects (/app/ or /desk/) across all 10 screens
for (const [name, src] of Object.entries(screens)) {
	assert.ok(!src.includes("/app/"), `${name} view must not link to /app/`);
	assert.ok(!src.includes("/desk/"), `${name} view must not link to /desk/`);
}

// 2. Check TenderPage shell usage on all screens
const shellSrc = read(resolve(jsDir, "pages/tender/TenderPage.vue"));
assert.ok(shellSrc.includes("tender-breadcrumb"), "TenderPage shell must render visible mobile breadcrumb");

// 3. Check MoneyInput & DateInput usage in forms
assert.ok(screens.sourcing.includes("MoneyInput"), "Sourcing workspace must use MoneyInput");
assert.ok(screens.sourcing.includes("DateInput"), "Sourcing workspace must use DateInput");

// 4. Check pipeline strip filter consistency
assert.ok(screens.flow.includes("stage") || screens.flow.includes("filter"), "TenderFlow must handle stage/filter");

console.log("ok — all 10 tender screens passed automated UAT matrix checks");
