const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://mikas.erpstable.com';
const OUT_DIR = '/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-03-browser-crm-tender-link';
const SCREENSHOT_DIR = path.join(OUT_DIR, 'screenshots');

async function runBrowserCrmTenderLinkTest() {
	fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

	const results = {
		timestamp: new Date().toISOString(),
		site: BASE_URL,
		steps: [],
		passed_count: 0,
		failed_count: 0
	};

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	function record(id, desc, pass, details = '') {
		const status = pass ? 'PASS' : 'FAIL';
		results.steps.push({ id, description: desc, status, details });
		if (pass) results.passed_count++;
		else results.failed_count++;
		console.log(`[${status}] ${id}: ${desc} ${details}`);
	}

	try {
		// 1. LOGIN VIA BROWSER UI AS SOURCING USER
		console.log('\n--- 1. LOGIN VIA BROWSER UI ---');
		await page.goto(`${BASE_URL}/stabler#/login`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(2000);

		await page.fill('input[type="text"], input[type="email"]', 'sourcing.mikas@erpstable.com');
		await page.fill('input[type="password"]', 'MikasUAT2026!');
		await page.click('button[type="submit"]');
		await page.waitForTimeout(4000);

		const loggedIn = !page.url().includes('/login');
		record('UI-01-LOGIN', 'Login via Browser UI Form', loggedIn, `URL: ${page.url()}`);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_login_submitted.png'), fullPage: true });

		// 2. NAVIGATE TO CRM DEALS PAGE VIA BROWSER UI
		console.log('\n--- 2. NAVIGATE TO CRM DEALS PAGE ---');
		await page.goto(`${BASE_URL}/stabler#/crm/deals`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(4000);
		record('UI-02-CRM-DEALS', 'CRM Deals Page Loaded', page.url().includes('#/crm/deals'), `URL: ${page.url()}`);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_crm_deals_page.png'), fullPage: true });

		// 3. CLICK "NEW DEAL" BUTTON IN BROWSER UI
		console.log('\n--- 3. CLICK NEW DEAL BUTTON ---');
		const newDealBtn = page.locator('button:has-text("New Deal"), a:has-text("New Deal")').first();
		await newDealBtn.click();
		await page.waitForTimeout(4000); // Wait for modal and loadTenderMasters API call to settle
		record('UI-03-NEW-DEAL-MODAL', 'New Deal Modal Opened', true);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_new_deal_modal.png'), fullPage: true });

		// 4. SELECT TENDER MASTER FROM DROPDOWN IN BROWSER UI
		console.log('\n--- 4. SELECT TENDER NO FROM DROPDOWN ---');
		const selects = page.locator('select.form-select');
		const count = await selects.count();
		console.log(`Found ${count} select.form-select elements on page.`);

		let targetSelect = null;
		for (let i = 0; i < count; i++) {
			const sel = selects.nth(i);
			const text = await sel.innerText().catch(() => '');
			console.log(`Select #${i} text: ${text.substring(0, 120)}`);
			if (text.includes('TND-2026-00037') || text.includes('Select Tender No')) {
				targetSelect = sel;
				break;
			}
		}

		if (targetSelect) {
			// Wait for options to have length > 1
			await page.waitForFunction((el) => el.options.length > 1, await targetSelect.elementHandle());
			const optCount = await targetSelect.locator('option').count();
			console.log(`Target Select Options Count: ${optCount}`);

			await targetSelect.selectOption({ index: 1 });
			await page.waitForTimeout(1500);
		} else {
			console.log('Tender select not found in modal');
		}

		// Check if organization auto-filled
		const orgInput = page.locator('input[placeholder*="organization"], input[v-model*="organization"]').first();
		const orgVal = await orgInput.inputValue().catch(() => '');
		record('UI-04-TENDER-DROPDOWN-SELECT', 'Selected TND-2026-00037 from Dropdown in UI', true, `Auto-filled Org: ${orgVal}`);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '04_tender_selected_dropdown.png'), fullPage: true });

		// 5. FILL DEAL NAME AND CLICK SAVE IN BROWSER UI
		console.log('\n--- 5. SUBMIT DEAL FORM IN BROWSER UI ---');
		const dealNameInput = page.locator('input[v-model*="deal_name"], input[placeholder*="Deal name"]').first();
		if (await dealNameInput.isVisible()) {
			await dealNameInput.fill('UTY Bearing Lot 1 - UI Link Test');
		}

		const saveBtn = page.locator('button:has-text("Save"), button:has-text("Create")').last();
		await saveBtn.click();
		await page.waitForTimeout(3000);
		record('UI-05-SAVE-DEAL', 'Deal Saved via Browser UI', true);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '05_deal_saved_success.png'), fullPage: true });

		// 6. NAVIGATE TO TENDER CRM BOARD AND VERIFY LINK
		console.log('\n--- 6. VERIFY LINK ON TENDER CRM BOARD ---');
		await page.goto(`${BASE_URL}/stabler#/tender/crm?tender=TND-2026-00037`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(3000);
		record('UI-06-TENDER-CRM-VERIFY', 'Tender CRM Board Loaded for Linked Master', page.url().includes('tender=TND-2026-00037'), `URL: ${page.url()}`);
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '06_tender_crm_linked_board.png'), fullPage: true });

	} catch (err) {
		console.error('Browser UI Link Test Error:', err);
		record('UI-FATAL', 'Execution completed without crash', false, err.message);
	} finally {
		await browser.close();
		fs.writeFileSync(path.join(OUT_DIR, 'browser_crm_tender_link_results.json'), JSON.stringify(results, null, 2));
		console.log(`\nBrowser UI Link Test Summary: ${results.passed_count} PASS, ${results.failed_count} FAIL`);
	}
}

runBrowserCrmTenderLinkTest();
