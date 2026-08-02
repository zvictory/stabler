import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const vuePath = path.join(__dirname, "../public/js/pages/tender/OperationsDesk.vue");
const source = fs.readFileSync(vuePath, "utf-8");

assert.ok(!source.includes("/app/"), "OperationsDesk.vue must not contain /app/ links");
assert.ok(!source.includes("table-striped"), "OperationsDesk.vue must not add table-striped manually");
assert.ok(source.includes("SkeletonRows"), "OperationsDesk.vue must use SkeletonRows for loading state");
assert.ok(source.includes("reqToken"), "OperationsDesk.vue must use reqToken for race-safe company/view switching");
assert.ok(source.includes("route.query") || source.includes("router.replace") || source.includes("router.push"), "OperationsDesk.vue must sync filter with URL query");

console.log("operations desk frontend contract: OK");
