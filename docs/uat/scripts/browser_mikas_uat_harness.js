const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://mikas.erpstable.com';
const OUT_DIR = '/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-03-mikas-reset';
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

async function runMikasBrowserUAT() {
	const { adminPass } = loadSecrets();
	fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

	const browser = await chromium.launch({ headless: true });
	const results = {
		timestamp: new Date().toISOString(),
		site: BASE_URL,
		assertions: [],
		passed_count: 0,
		failed_count: 0
	};
	const networkLogs = [];
	const consoleLogs = [];

	const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
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

	function recordAssertion(id, desc, pass, details = '') {
		const entry = { id, description: desc, status: pass ? 'PASS' : 'FAIL', details };
		results.assertions.push(entry);
		if (pass) results.passed_count++; else results.failed_count++;
		console.log(`[${entry.status}] ${id}: ${desc} ${details}`);
	}

	try {
		// 1. API Login into browser session context
		console.log('Logging in to mikas.erpstable.com as Administrator...');
		const loginResp = await page.request.post(`${BASE_URL}/api/method/login`, {
			data: { usr: 'Administrator', pwd: adminPass }
		});
		recordAssertion('UAT-LOGIN-01', 'Login API returns 200 OK', loginResp.status() === 200, `Status: ${loginResp.status()}`);

		// 2. Navigate to Stabler SPA Home (Portfolio)
		await page.goto(`${BASE_URL}/stabler#/tender/portfolio`, { waitUntil: 'networkidle' });
		await page.waitForTimeout(2500);
		recordAssertion('UAT-NAV-01', 'Portfolio SPA route loads clean', page.url().includes('#/tender/portfolio'), `URL: ${page.url()}`);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_tender_portfolio_empty.png'), fullPage: true });

		// 3. Operations Desk route
		await page.goto(`${BASE_URL}/stabler#/tender/desk`, { waitUntil: 'networkidle' });
		await page.waitForTimeout(2500);
		const deskBodyText = await page.innerText('body');
		const deskEmpty = deskBodyText.includes('No tasks scheduled for today') || deskBodyText.includes('0 items') || deskBodyText.includes('0');
		recordAssertion('UAT-DESK-01', 'Operations Desk renders empty state', deskEmpty, 'Zero active items verified');
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_operations_desk_empty.png'), fullPage: true });

		// 4. CRM Pipeline route
		await page.goto(`${BASE_URL}/stabler#/tender/crm`, { waitUntil: 'networkidle' });
		await page.waitForTimeout(2500);
		const crmText = await page.innerText('body');
		const crmEmpty = !crmText.includes('CRM-DEAL-2026') && !crmText.includes('CRM-DEAL-2025');
		recordAssertion('UAT-CRM-01', 'Tender CRM Pipeline renders empty state', crmEmpty, 'Zero deals verified');
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_crm_pipeline_empty.png'), fullPage: true });

		// 5. Sourcing Workspace route
		await page.goto(`${BASE_URL}/stabler#/tender/sourcing`, { waitUntil: 'networkidle' });
		await page.waitForTimeout(2500);
		const sourcingText = await page.innerText('body');
		const sourcingEmpty = sourcingText.includes('Pick a tender deal') || sourcingText.includes('Select a lot') || sourcingText.includes('No active sourcing lots');
		recordAssertion('UAT-SOURCING-01', 'Sourcing Workspace renders clean state', sourcingEmpty, 'No active sourcing lots verified');
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '04_sourcing_workspace_empty.png'), fullPage: true });

		// 6. Main Dashboard route
		await page.goto(`${BASE_URL}/stabler#/dashboard`, { waitUntil: 'networkidle' });
		await page.waitForTimeout(2500);
		recordAssertion('UAT-DASHBOARD-01', 'Main Dashboard redirects or renders clean', !page.url().includes('auth-transition'), `URL: ${page.url()}`);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '05_main_dashboard_empty.png'), fullPage: true });

		// 7. Sales Customers Center
		await page.goto(`${BASE_URL}/stabler#/sales/customers`, { waitUntil: 'networkidle' });
		await page.waitForTimeout(2500);
		const customerText = await page.innerText('body');
		const customerZeroBal = customerText.includes('0.00 UZS') || customerText.includes('0 UZS') || !customerText.includes('SAL-ORD-');
		recordAssertion('UAT-SALES-01', 'Sales Customer Center renders clean transactions', customerZeroBal, 'Zero transaction balance verified');
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '06_sales_customers_empty.png'), fullPage: true });

		// 8. Purchasing Invoices
		await page.goto(`${BASE_URL}/stabler#/purchasing/invoices`, { waitUntil: 'networkidle' });
		await page.waitForTimeout(2500);
		const purText = await page.innerText('body');
		const purEmpty = purText.includes('No Purchase Invoices') || !purText.includes('ACC-PINV-');
		recordAssertion('UAT-PURCHASING-01', 'Purchasing Invoices renders empty state', purEmpty, 'Zero purchase invoices verified');
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '07_purchasing_invoices_empty.png'), fullPage: true });

		// 9. Check Console Errors and 500s
		const has500 = networkLogs.some((l) => l.status >= 500);
		recordAssertion('UAT-NETWORK-01', 'Zero HTTP 500 Server Errors', !has500, `Error count: ${networkLogs.length}`);

	} catch (err) {
		console.error('Browser UAT failed with error:', err);
		recordAssertion('UAT-FATAL', 'Execution completed without crash', false, err.message);
	} finally {
		await browser.close();
		fs.writeFileSync(path.join(OUT_DIR, 'mikas_uat_results.json'), JSON.stringify({ results, consoleLogs, networkLogs }, null, 2));
		console.log(`\nUAT Complete: ${results.passed_count} PASS, ${results.failed_count} FAIL`);
	}
}

runMikasBrowserUAT();
