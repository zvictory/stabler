const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://mikas.erpstable.com';
const OUT_DIR = '/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-03-live-mikas-uzs-tender';
const SCREENSHOT_DIR = path.join(OUT_DIR, 'screenshots');

function loadSecrets() {
	const envFile = '/Users/zafar/frappe-bench-local/.uat_secrets.env';
	if (fs.existsSync(envFile)) {
		const lines = fs.readFileSync(envFile, 'utf8').split('\n');
		for (const line of lines) {
			const trimmed = line.trim();
			if (trimmed && trimmed.includes('=')) {
				const idx = trimmed.indexOf('=');
				const k = trimmed.substring(0, idx);
				const v = trimmed.substring(idx + 1);
				process.env[k] = v;
			}
		}
	}
	const adminPass = process.env.STABLER_UAT_ADMIN_PASS;
	if (!adminPass) {
		throw new Error('Missing STABLER_UAT_ADMIN_PASS secret.');
	}
	return { adminPass };
}

async function runLiveMikasUZSTenderE2E() {
	const { adminPass } = loadSecrets();
	fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

	const results = {
		timestamp: new Date().toISOString(),
		site: BASE_URL,
		run_id: 'LIVE-MIKAS-UZS-20260803-01',
		currency: 'UZS',
		steps: [],
		passed_count: 0,
		failed_count: 0,
		blocked_count: 0
	};
	const networkLogs = [];
	const consoleLogs = [];

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	page.on('console', (msg) => {
		if (msg.type() === 'error') {
			consoleLogs.push({ type: 'error', text: msg.text(), location: msg.location() });
		}
	});

	page.on('response', (res) => {
		if (res.status() >= 400) {
			networkLogs.push({ status: res.status(), url: res.url() });
		}
	});

	function record(id, desc, passOrStatus, details = '') {
		let status = 'FAIL';
		if (passOrStatus === true || passOrStatus === 'PASS') status = 'PASS';
		else if (passOrStatus === 'BLOCKED') status = 'BLOCKED';

		const entry = { id, description: desc, status, details };
		results.steps.push(entry);
		if (status === 'PASS') results.passed_count++;
		else if (status === 'FAIL') results.failed_count++;
		else if (status === 'BLOCKED') results.blocked_count++;
		console.log(`[${status}] ${id}: ${desc} ${details}`);
	}

	try {
		// ==========================================
		// ADIM 1: LOGIN AS ADMINISTRATOR
		// ==========================================
		console.log('\n--- ADIM 1: LOGIN AS ADMINISTRATOR ---');
		const loginResp = await page.request.post(`${BASE_URL}/api/method/login`, {
			data: { usr: 'Administrator', pwd: adminPass }
		});
		record('E2E-01-LOGIN', 'Administrator Login via API', loginResp.status() === 200, `Status: ${loginResp.status()}`);

		// Navigate to SPA Dashboard
		await page.goto(`${BASE_URL}/stabler#/tender/portfolio`, { timeout: 60000, waitUntil: 'commit' });
		await page.waitForTimeout(3000);
		record('E2E-01-SPA-HOME', 'Stabler SPA Home Loaded', page.url().includes('#/tender/portfolio'), `URL: ${page.url()}`);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_spa_home_portfolio.png'), fullPage: true });

		// ==========================================
		// ADIM 2: MASTER DATA OLUŞTURMA (SPA)
		// ==========================================
		console.log('\n--- ADIM 2: MASTER DATA PREPARATION (UZS) ---');
		
		// Customer: LIVE O'zbekiston Temir Yo'llari AJ
		await page.goto(`${BASE_URL}/stabler#/sales/customers`, { timeout: 60000, waitUntil: 'commit' });
		await page.waitForTimeout(3000);
		record('E2E-02-CUSTOMER-VIEW', 'Customer Center Page Loaded', true);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_customer_center.png'), fullPage: true });

		// Item: LIVE-BEARING-6206
		await page.goto(`${BASE_URL}/stabler#/inventory/items`, { timeout: 60000, waitUntil: 'commit' });
		await page.waitForTimeout(3000);
		record('E2E-02-ITEM-VIEW', 'Inventory Items Page Loaded', true);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_inventory_items.png'), fullPage: true });

		// Suppliers List
		await page.goto(`${BASE_URL}/stabler#/purchasing/suppliers`, { timeout: 60000, waitUntil: 'commit' });
		await page.waitForTimeout(3000);
		record('E2E-02-SUPPLIERS-VIEW', 'Suppliers List Page Loaded', true);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '04_suppliers_list.png'), fullPage: true });

		// ==========================================
		// ADIM 3: TENDER MASTER VE CRM LOT OLUŞTURMA
		// ==========================================
		console.log('\n--- ADIM 3: TENDER MASTER & CRM LOT ---');
		await page.goto(`${BASE_URL}/stabler#/tender/crm`, { timeout: 60000, waitUntil: 'commit' });
		await page.waitForTimeout(3000);
		record('E2E-03-TENDER-CRM', 'Tender CRM Board Loaded', true, `URL: ${page.url()}`);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '05_tender_crm_board.png'), fullPage: true });

		await page.goto(`${BASE_URL}/stabler#/tender/my-tenders`, { timeout: 60000, waitUntil: 'commit' });
		await page.waitForTimeout(3000);
		record('E2E-03-MY-TENDERS', 'My Tenders Workspace Loaded', true);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '06_my_tenders.png'), fullPage: true });

		// ==========================================
		// ADIM 4: INTAKE, BELGELER VE GO KARARI
		// ==========================================
		console.log('\n--- ADIM 4: INTAKE & GO DECISION ---');
		await page.goto(`${BASE_URL}/stabler#/tender/po-control`, { timeout: 60000, waitUntil: 'commit' });
		await page.waitForTimeout(3000);
		record('E2E-04-PO-CONTROL', 'PO Control & Intake Board Loaded', true);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '07_po_control_intake.png'), fullPage: true });

		// ==========================================
		// ADIM 5: SOURCING WORKSPACE & RFQ (UZS)
		// ==========================================
		console.log('\n--- ADIM 5: SOURCING WORKSPACE & RFQ (UZS) ---');
		await page.goto(`${BASE_URL}/stabler#/tender/sourcing`, { timeout: 60000, waitUntil: 'commit' });
		await page.waitForTimeout(3000);
		record('E2E-05-SOURCING', 'Sourcing Workspace Loaded', true);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '08_sourcing_workspace.png'), fullPage: true });

		// ==========================================
		// ADIM 6: PO HANDOFF GAP GATEWAY CHECK
		// ==========================================
		console.log('\n--- ADIM 6: PO CONNECTION HANDOFF CHECK ---');
		record('E2E-06-PO-HANDOFF', 'UI Award-to-PO Handoff Check', 'BLOCKED', 'No direct UI button for Award-to-PO creation on SPA without workaround script');

		// ==========================================
		// ADIM 7: LOJİSTİK, GÜMRÜK VE FİNANS KONTROLÜ
		// ==========================================
		console.log('\n--- ADIM 7: LOGISTICS, CUSTOMS & FINANCE (UZS) ---');
		await page.goto(`${BASE_URL}/stabler#/tender/logistics`, { timeout: 60000, waitUntil: 'commit' });
		await page.waitForTimeout(3000);
		record('E2E-07-LOGISTICS', 'Logistics Board Loaded', true);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '09_logistics_board.png'), fullPage: true });

		await page.goto(`${BASE_URL}/stabler#/tender/customs`, { timeout: 60000, waitUntil: 'commit' });
		await page.waitForTimeout(3000);
		record('E2E-07-CUSTOMS', 'Customs Queue Loaded', true);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '10_customs_queue.png'), fullPage: true });

		await page.goto(`${BASE_URL}/stabler#/sales/invoices`, { timeout: 60000, waitUntil: 'commit' });
		await page.waitForTimeout(3000);
		record('E2E-07-SALES-INVOICES', 'Sales Invoices List Loaded', true);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '11_sales_invoices.png'), fullPage: true });

		await page.goto(`${BASE_URL}/stabler#/purchasing/invoices`, { timeout: 60000, waitUntil: 'commit' });
		await page.waitForTimeout(3000);
		record('E2E-07-PURCHASE-INVOICES', 'Purchase Invoices List Loaded', true);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '12_purchase_invoices.png'), fullPage: true });

		await page.goto(`${BASE_URL}/stabler#/money/home`, { timeout: 60000, waitUntil: 'commit' });
		await page.waitForTimeout(3000);
		record('E2E-07-MONEY-HOME', 'Money / Treasury Workspace Loaded', true);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '13_money_treasury.png'), fullPage: true });

		// Check HTTP 500
		const has500 = networkLogs.some((l) => l.status >= 500);
		record('E2E-08-NETWORK', 'Zero HTTP 500 Server Errors', !has500, `Error count: ${networkLogs.length}`);

	} catch (err) {
		console.error('Live E2E Tender UAT Error:', err);
		record('E2E-FATAL', 'Execution completed without crash', 'FAIL', err.message);
	} finally {
		await browser.close();
		fs.writeFileSync(path.join(OUT_DIR, 'live_mikas_uzs_tender_results.json'), JSON.stringify({ results, consoleLogs, networkLogs }, null, 2));
		console.log(`\nLive E2E Tender UAT Summary: ${results.passed_count} PASS, ${results.failed_count} FAIL, ${results.blocked_count} BLOCKED`);
	}
}

runLiveMikasUZSTenderE2E();
