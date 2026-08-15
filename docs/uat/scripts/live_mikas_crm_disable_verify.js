// Post-disable verification: CRM menu hidden, /crm/* redirects, /tender/crm works.
// Run: node docs/uat/scripts/live_mikas_crm_disable_verify.js
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://mikas.erpstable.com';
const OUT_DIR = '/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-15-mikas-crm-disable';
const SCREENSHOT_DIR = path.join(OUT_DIR, 'screenshots');

function loadSecrets() {
	const envFile = '/Users/zafar/frappe-bench-local/.uat_secrets.env';
	if (fs.existsSync(envFile)) {
		for (const line of fs.readFileSync(envFile, 'utf-8').split('\n')) {
			const trimmed = line.trim();
			if (trimmed && trimmed.includes('=')) {
				const idx = trimmed.indexOf('=');
				process.env[trimmed.substring(0, idx)] = trimmed.substring(idx + 1);
			}
		}
	}
	const adminPass = process.env.STABLER_UAT_ADMIN_PASS;
	if (!adminPass) throw new Error('Missing STABLER_UAT_ADMIN_PASS secret.');
	return { adminPass };
}

async function main() {
	const { adminPass } = loadSecrets();
	fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	const loginResp = await page.request.post(`${BASE_URL}/api/method/login`, {
		data: { usr: 'Administrator', pwd: adminPass }
	});
	if (loginResp.status() !== 200) throw new Error(`Login failed: ${loginResp.status()}`);

	const results = { timestamp: new Date().toISOString(), site: BASE_URL, checks: [] };
	function record(id, desc, pass, details = '') {
		results.checks.push({ id, description: desc, status: pass ? 'PASS' : 'FAIL', details });
		console.log(`[${pass ? 'PASS' : 'FAIL'}] ${id}: ${desc} ${details}`);
	}

	// 1) Sidebar on a landing page: no anchor may point at the standalone /crm module
	// (TenderNav legitimately renders a "Tender CRM" -> /tender/crm item; text match is not enough)
	await page.goto(`${BASE_URL}/stabler#/tender/crm`, { timeout: 60000, waitUntil: 'commit' });
	await page.waitForTimeout(4000);
	const sidebarText = (await page.locator('body').innerText()).trim();
	const crmAnchors = await page.locator('a[href$="#/crm"], a[href*="#/crm/"], a[href="/stabler#/crm"]').count();
	const tenderCrmAnchors = await page.locator('a[href$="#/tender/crm"]').count();
	await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'tender_crm_page.png') });
	record('CRM-01', 'Tender CRM page loads', sidebarText.length > 0, page.url());
	record('CRM-02', 'No standalone CRM menu entry in sidebar (no /crm anchors)', crmAnchors === 0, `anchors=${crmAnchors}`);
	record('CRM-02b', 'Tender CRM nav item still present', tenderCrmAnchors > 0, `anchors=${tenderCrmAnchors}`);

	// 2) Direct navigation to /crm/leads must redirect away (module disabled)
	await page.goto(`${BASE_URL}/stabler#/crm/leads`, { timeout: 60000, waitUntil: 'commit' });
	await page.waitForTimeout(4000);
	const redirected = !page.url().includes('/crm/leads');
	await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'crm_leads_redirect.png') });
	record('CRM-03', '/crm/leads redirects (module disabled)', redirected, `landed on ${page.url()}`);

	// 3) /tender/crm still reachable and renders its board
	await page.goto(`${BASE_URL}/stabler#/tender/crm`, { timeout: 60000, waitUntil: 'commit' });
	await page.waitForTimeout(4000);
	const stillWorks = page.url().includes('/tender/crm');
	record('CRM-04', '/tender/crm still accessible', stillWorks, page.url());

	await browser.close();
	fs.writeFileSync(path.join(OUT_DIR, 'mikas_crm_disable_results.json'), JSON.stringify(results, null, 1));
	const failed = results.checks.filter((c) => c.status === 'FAIL').length;
	console.log(failed === 0 ? 'ALL CHECKS PASS ✓' : `${failed} CHECKS FAILED!`);
	process.exit(failed === 0 ? 0 : 1);
}

main().catch((e) => { console.error(e); process.exit(1); });
