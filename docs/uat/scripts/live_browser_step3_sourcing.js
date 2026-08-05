const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://mikas.erpstable.com';
const OUT_DIR = '/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-03-step3-sourcing';
const SCREENSHOT_DIR = path.join(OUT_DIR, 'screenshots');

async function runStep3Sourcing() {
	fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();
	page.setDefaultTimeout(35000);

	const results = {
		timestamp: new Date().toISOString(),
		site: BASE_URL,
		quotations: [],
		sourcing_decision: null,
		approval: null
	};

	try {
		// 1. LOGIN VIA FRONTEND AS SOURCING USER
		console.log('\n--- 1. LOGIN AS SOURCING USER ---');
		await page.goto(`${BASE_URL}/stabler#/login`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(2000);

		await page.fill('input[type="text"], input[type="email"]', 'sourcing.mikas@erpstable.com');
		await page.fill('input[type="password"]', 'MikasUAT2026!');
		await page.click('button[type="submit"]');
		await page.waitForTimeout(4000);

		await page.goto(`${BASE_URL}/stabler#/tender/crm`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(3000);

		console.log(`Logged in URL: ${page.url()}`);

		// 2. CREATE 5 SUPPLIER QUOTATIONS VIA STABLER API (UZS)
		console.log('\n--- 2. CREATING 5 SUPPLIER QUOTATIONS (UZS) ---');
		const dealId = 'CRM-DEAL-2026-00098';

		const quotesData = [
			{ supplier: 'Tashkent Bearing Factory LLC', qty: 100, rate: 135000, total: 13500000 },
			{ supplier: 'Ural Components CJSC', qty: 100, rate: 129600, total: 12960000 },
			{ supplier: 'Samarkand Industrial Supply', qty: 100, rate: 142000, total: 14200000 },
			{ supplier: 'SinoBearings Shanghai Ltd', qty: 100, rate: 148000, total: 14800000 },
			{ supplier: 'Fergana Tech Trade', qty: 100, rate: 150000, total: 15000000 }
		];

		const createdQuotes = [];

		for (const q of quotesData) {
			const res = await page.evaluate(async ({ deal, data }) => {
				const r = await fetch('/api/method/stabler.api.sourcing.save_supplier_quotation', {
					method: 'POST',
					headers: {
						'Content-Type': 'application/json',
						'X-Frappe-CSRF-Token': window.__STABLER__?.csrfToken || ''
					},
					body: JSON.stringify({
						deal: deal,
						supplier: data.supplier,
						currency: 'UZS',
						items: [
							{
								item_code: 'UAT-BEARING-6206',
								qty: data.qty,
								rate: data.rate,
								amount: data.total
							}
						],
						company: 'Mikas'
					})
				});
				return await r.json();
			}, { deal: dealId, data: q });

			if (res.message) {
				const sqName = res.message.name || res.message;
				createdQuotes.push({ name: sqName, supplier: q.supplier, amount: q.total });
				console.log(`Created Supplier Quotation: ${sqName} for ${q.supplier} (${q.total} UZS)`);
			} else {
				console.error(`Failed quote for ${q.supplier}:`, res);
			}
		}

		results.quotations = createdQuotes;

		// 3. NAVIGATE TO SOURCING COMPARISON BOARD IN BROWSER UI
		console.log('\n--- 3. NAVIGATE TO SOURCING BOARD IN BROWSER UI ---');
		await page.goto(`${BASE_URL}/stabler#/tender/sourcing?deal=${encodeURIComponent(dealId)}`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(4000);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_sourcing_comparison_board.png'), fullPage: true });

		// 4. SUBMIT DRAFT SOURCING DECISION SELECTING URAL COMPONENTS (WINNER)
		console.log('\n--- 4. SUBMIT SOURCING DECISION (WINNER: Ural Components) ---');
		const winnerQuote = createdQuotes.find(q => q.supplier.includes('Ural Components'));
		if (winnerQuote) {
			const sourcingRes = await page.evaluate(async ({ deal, quoteName }) => {
				const r = await fetch('/api/method/stabler.api.sourcing.save_sourcing_decision', {
					method: 'POST',
					headers: {
						'Content-Type': 'application/json',
						'X-Frappe-CSRF-Token': window.__STABLER__?.csrfToken || ''
					},
					body: JSON.stringify({
						deal: deal,
						selected_quotation: quoteName,
						selection_reason: 'Lowest landed cost (12,960,000 UZS) and compliant technical specification for UTY railway bearings.',
						technical_result: 'Compliant',
						company: 'Mikas'
					})
				});
				return await r.json();
			}, { deal: dealId, quoteName: winnerQuote.name });

			console.log('Sourcing Decision Result:', sourcingRes.message);
			results.sourcing_decision = sourcingRes.message;
		}

		await page.goto(`${BASE_URL}/stabler#/tender/sourcing?deal=${encodeURIComponent(dealId)}`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(4000);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_sourcing_decision_recorded.png'), fullPage: true });

		// 5. LOGIN AS DIRECTOR & APPROVE SOURCING DECISION
		console.log('\n--- 5. DIRECTOR APPROVAL ---');
		// Clear session and login as Director via API
		await page.request.post(`${BASE_URL}/api/method/logout`);
		await context.clearCookies();

		await page.goto(`${BASE_URL}/stabler#/login`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(2000);

		await page.fill('input[type="text"], input[type="email"]', 'director.mikas@erpstable.com');
		await page.fill('input[type="password"]', 'MikasUAT2026!');
		await page.click('button[type="submit"]');
		await page.waitForTimeout(4000);

		await page.goto(`${BASE_URL}/stabler#/tender/sourcing?deal=${encodeURIComponent(dealId)}`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(3000);

		const decId = results.sourcing_decision?.name || 'TSD-2026-00001';
		if (decId) {
			const approveRes = await page.evaluate(async ({ decName }) => {
				const r = await fetch('/api/method/stabler.api.sourcing.approve_sourcing_decision', {
					method: 'POST',
					headers: {
						'Content-Type': 'application/json',
						'X-Frappe-CSRF-Token': window.__STABLER__?.csrfToken || ''
					},
					body: JSON.stringify({
						name: decName,
						company: 'Mikas'
					})
				});
				return await r.json();
			}, { decName: decId });

			console.log('Director Approval Result:', approveRes.message);
			results.approval = approveRes.message;
		}

		// Navigate to Sourcing Board & Level 2 Lot Board as Director
		await page.goto(`${BASE_URL}/stabler#/tender/sourcing?deal=${encodeURIComponent(dealId)}`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(4000);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_sourcing_approved_director.png'), fullPage: true });

		await page.goto(`${BASE_URL}/stabler#/tender/crm?tender=TND-2026-00037`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(4000);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '04_tender_crm_after_approval.png'), fullPage: true });

	} catch (err) {
		console.error('Step 3 Sourcing Error:', err);
	} finally {
		await browser.close();
		fs.writeFileSync(path.join(OUT_DIR, 'step3_sourcing_results.json'), JSON.stringify(results, null, 2));
		console.log('\nStep 3 Sourcing Execution Complete.');
	}
}

runStep3Sourcing();
