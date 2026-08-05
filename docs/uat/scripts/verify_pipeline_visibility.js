const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://mikas.erpstable.com';
const OUT_DIR = '/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-03-pipeline-verify';
const SCREENSHOT_DIR = path.join(OUT_DIR, 'screenshots');

async function runPipelineVerify() {
	fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();
	page.setDefaultTimeout(45000);

	const report = [];

	try {
		// Login properly via browser UI form
		await page.goto(`${BASE_URL}/stabler#/login`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(2000);
		await page.fill('input[type="text"], input[type="email"]', 'director.mikas@erpstable.com');
		await page.fill('input[type="password"]', 'MikasUAT2026!');
		await page.click('button[type="submit"]');
		await page.waitForTimeout(5000);

		console.log(`LoggedIn URL: ${page.url()}`);

		// 1. Level 1 Master Tender Board
		console.log('\n--- 1. LEVEL 1 MASTER TENDER BOARD ---');
		await page.goto(`${BASE_URL}/stabler#/tender/crm`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(4000);
		const l1Text = await page.innerText('body');
		const l1HasTender = l1Text.includes('UTY Demiryolu Rulman Tedariği 2026') || l1Text.includes('TND-2026-00037');
		console.log(`L1 Board Has Tender: ${l1HasTender}`);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_level1_master_board.png'), fullPage: true });
		report.push({ name: 'Level 1 Master Board', url: page.url(), visible: l1HasTender, snippet: l1Text.substring(0, 300) });

		// 2. Level 2 Tender CRM Board
		console.log('\n--- 2. LEVEL 2 TENDER CRM BOARD ---');
		await page.goto(`${BASE_URL}/stabler#/tender/crm?tender=TND-2026-00037`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(4000);
		const l2Text = await page.innerText('body');
		const l2HasDeal = l2Text.includes('CRM-DEAL-2026-00098') || l2Text.includes("O'zbekiston Temir Yo'llari AJ") || l2Text.includes('UTY');
		console.log(`L2 Board Has Deal: ${l2HasDeal}`);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_level2_lot_board.png'), fullPage: true });
		report.push({ name: 'Level 2 Tender CRM Board', url: page.url(), visible: l2HasDeal, snippet: l2Text.substring(0, 300) });

		// 3. Tender Portfolio Board
		console.log('\n--- 3. TENDER PORTFOLIO BOARD ---');
		await page.goto(`${BASE_URL}/stabler#/tender/portfolio`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(4000);
		const pfText = await page.innerText('body');
		const pfHasTender = pfText.includes('UTY') || pfText.includes('TND-2026-00037') || pfText.includes('Demiryolu');
		console.log(`Portfolio Board Has Tender: ${pfHasTender}`);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_portfolio_board.png'), fullPage: true });
		report.push({ name: 'Tender Portfolio Board', url: page.url(), visible: pfHasTender, snippet: pfText.substring(0, 300) });

		// 4. CRM Deals Board
		console.log('\n--- 4. CRM DEALS BOARD ---');
		await page.goto(`${BASE_URL}/stabler#/crm/deals`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(4000);
		const crmText = await page.innerText('body');
		const crmHasDeal = crmText.includes('CRM-DEAL-2026-00098') || crmText.includes("O'zbekiston Temir Yo'llari AJ") || crmText.includes('UTY');
		console.log(`CRM Deals Board Has Deal: ${crmHasDeal}`);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '04_crm_deals_board.png'), fullPage: true });
		report.push({ name: 'CRM Deals Board', url: page.url(), visible: crmHasDeal, snippet: crmText.substring(0, 300) });

	} catch (err) {
		console.error('Pipeline Verify Error:', err);
	} finally {
		await browser.close();
		fs.writeFileSync(path.join(OUT_DIR, 'pipeline_report.json'), JSON.stringify(report, null, 2));
		console.log('\nPipeline Verification Complete.');
	}
}

runPipelineVerify();
