import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const jsDir = resolve(here, "../public/js");

const read = (file) => readFileSync(file, "utf8");

const crmSrc = read(resolve(jsDir, "pages/tender/TenderCrm.vue"));
const directorSrc = read(resolve(jsDir, "pages/tender/DirectorBoard.vue"));
const sourcingSrc = read(resolve(jsDir, "pages/tender/SourcingWorkspace.vue"));
const docsSrc = read(resolve(jsDir, "pages/tender/TenderDocuments.vue"));
const poControlSrc = read(resolve(jsDir, "pages/tender/PoControlBoard.vue"));
const pageShellSrc = read(resolve(jsDir, "pages/tender/TenderPage.vue"));

// 1. Lot CRM actions carry tender and deal context
assert.ok(
	crmSrc.includes("sourcingLocation") || crmSrc.includes("useTenderContext"),
	"TenderCrm must pass tender context to lot workspaces using useTenderContext",
);
assert.ok(
	crmSrc.includes("sourcingLocation") && crmSrc.includes("poControlLocation"),
	"TenderCrm drawer actions must carry route query context (sourcing & poControl)",
);

// 2. DirectorBoard row navigation preserves phase and tender context
assert.ok(
	directorSrc.includes("buildTenderQuery") || (directorSrc.includes("route.query") && directorSrc.includes("po-control")),
	"DirectorBoard row navigation must carry phase filter and tender context to PO Control",
);

// 3. TenderPage shell supports mobile breadcrumb returning to parent tender
assert.ok(
	pageShellSrc.includes("tender-breadcrumb") && pageShellSrc.includes("parentTender"),
	"TenderPage shell must render visible mobile breadcrumb for parent tender",
);

// 4. No Desk redirects anywhere in tender SPA views
for (const file of [crmSrc, directorSrc, sourcingSrc, docsSrc, poControlSrc, pageShellSrc]) {
	assert.ok(!file.includes("/app/"), "Tender views must never link to /app/");
	assert.ok(!file.includes("/desk/"), "Tender views must never link to /desk/");
}

console.log("ok — tender navigation & context contracts verified");
