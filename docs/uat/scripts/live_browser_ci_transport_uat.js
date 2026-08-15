const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://msa.erpstable.com';
const OUT_DIR = path.join(__dirname, '../evidence/2026-08-15-ci-transport-uat');
const SCREENSHOT_DIR = path.join(OUT_DIR, 'screenshots');
const ARTIFACT_DIR = '/Users/zafar/.gemini/antigravity/brain/56e2e62a-4fc4-46b8-a3fe-5fda74c5cfba';

fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

async function runCiTransportUAT() {
	console.log(`\n=== 🚀 Starting Real Browser Playwright UAT on ${BASE_URL} ===`);

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
	const page = await context.newPage();

	// 1. LOGIN
	console.log('\n--- 1. Login via SPA Login Page ---');
	await page.goto(`${BASE_URL}/stabler#/login`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(1000);

	await page.fill('#login-user', 'zafar@stable.uz');
	await page.fill('#login-pass', 'MsaUAT2026!');
	await page.click('button.login-submit');

	await page.waitForURL('**/stabler#/**', { timeout: 15000 });
	await page.waitForTimeout(2000);
	console.log('✅ Login successful! Current URL:', page.url());

	// 2. Fetch Commercial Invoices List
	console.log('\n--- 2. Navigating to Commercial Invoices List ---');
	await page.goto(`${BASE_URL}/stabler#/imports/commercial-invoices`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);

	const ciLinks = await page.evaluate(() => {
		const links = Array.from(document.querySelectorAll('table tbody tr a'));
		return links.map(a => ({
			text: a.innerText.trim(),
			href: a.getAttribute('href')
		})).filter(item => item.href && item.href.includes('/commercial-invoices/'));
	});

	console.log(`Found ${ciLinks.length} Commercial Invoices on live site:`);
	ciLinks.slice(0, 8).forEach(c => console.log(` - ${c.text} -> ${c.href}`));

	const listScreenshot = path.join(SCREENSHOT_DIR, '00_commercial_invoices_list.png');
	await page.screenshot({ path: listScreenshot, fullPage: true });
	fs.copyFileSync(listScreenshot, path.join(ARTIFACT_DIR, '00_commercial_invoices_list.png'));

	// Target list to test: CI-2026-00279, CI-2026-04387, plus first 2 from list
	const targets = ['CI-2026-00279', 'CI-2026-04387'];
	for (const link of ciLinks.slice(0, 3)) {
		const name = link.href.split('/').pop();
		if (!targets.includes(name)) {
			targets.push(name);
		}
	}

	for (const targetCI of targets) {
		console.log(`\n======================================================`);
		console.log(`--- 3. Testing CI Form: ${targetCI} ---`);
		const targetUrl = `${BASE_URL}/stabler#/imports/commercial-invoices/${targetCI}`;
		
		await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(4000);

		const currentUrl = page.url();
		console.log(`Navigated to: ${currentUrl}`);

		// Check for error alert or form loaded
		const notFound = await page.locator('text=not found, text=Unknown Commercial Invoice, text=404').first().isVisible().catch(() => false);
		if (notFound) {
			console.log(`⚠️ Note: ${targetCI} is not present on this database.`);
			const errScreenshot = path.join(SCREENSHOT_DIR, `${targetCI}_not_found.png`);
			await page.screenshot({ path: errScreenshot });
			continue;
		}

		// Full page screenshot
		const fullScreenshotPath = path.join(SCREENSHOT_DIR, `${targetCI}_full_page.png`);
		await page.screenshot({ path: fullScreenshotPath, fullPage: true });
		fs.copyFileSync(fullScreenshotPath, path.join(ARTIFACT_DIR, `${targetCI}_full_page.png`));
		console.log(`📸 Full page screenshot captured for ${targetCI}`);

		// Scroll to Transport Invoices section
		const transportHeader = page.locator('h3:has-text("Transport"), h4:has-text("Linked Transport Bills")').first();
		const transportVisible = await transportHeader.isVisible().catch(() => false);
		console.log(`Transport Section visible on ${targetCI}: ${transportVisible}`);

		if (transportVisible) {
			await transportHeader.scrollIntoViewIfNeeded();
			await page.waitForTimeout(1000);
			const transScreenshotPath = path.join(SCREENSHOT_DIR, `${targetCI}_transport_section.png`);
			await page.screenshot({ path: transScreenshotPath });
			fs.copyFileSync(transScreenshotPath, path.join(ARTIFACT_DIR, `${targetCI}_transport_section.png`));
			console.log(`📸 Transport section screenshot saved`);
		}

		// Check Link Transport Bill button & Modal
		const linkBtn = page.locator('button:has-text("Link transport bill")').first();
		const linkBtnVisible = await linkBtn.isVisible().catch(() => false);
		console.log(`'Link transport bill' button visible: ${linkBtnVisible}`);

		if (linkBtnVisible) {
			await linkBtn.click();
			await page.waitForTimeout(1500);
			const modalScreenshotPath = path.join(SCREENSHOT_DIR, `${targetCI}_link_modal.png`);
			await page.screenshot({ path: modalScreenshotPath });
			fs.copyFileSync(modalScreenshotPath, path.join(ARTIFACT_DIR, `${targetCI}_link_modal.png`));
			console.log(`📸 Link Transport Modal screenshot saved`);

			// Switch to "Create new transport invoice" tab
			const createTab = page.locator('a:has-text("Create new transport invoice"), button:has-text("Create new transport invoice")').first();
			if (await createTab.isVisible().catch(() => false)) {
				await createTab.click();
				await page.waitForTimeout(1000);
				const createTabScreenshotPath = path.join(SCREENSHOT_DIR, `${targetCI}_create_tab.png`);
				await page.screenshot({ path: createTabScreenshotPath });
				fs.copyFileSync(createTabScreenshotPath, path.join(ARTIFACT_DIR, `${targetCI}_create_tab.png`));
				console.log(`📸 Create Transport Invoice Tab screenshot saved`);
			}

			// Close modal
			const closeBtn = page.locator('button:has-text("Close"), .btn-close').first();
			if (await closeBtn.isVisible().catch(() => false)) {
				await closeBtn.click();
				await page.waitForTimeout(500);
			}
		}

		// Check Landed Cost (UZS) Card
		const landedCostHeader = page.locator('h3:has-text("Landed cost (UZS)")').first();
		const lcVisible = await landedCostHeader.isVisible().catch(() => false);
		console.log(`Landed cost (UZS) card visible on ${targetCI}: ${lcVisible}`);

		if (lcVisible) {
			await landedCostHeader.scrollIntoViewIfNeeded();
			await page.waitForTimeout(1000);
			const lcScreenshotPath = path.join(SCREENSHOT_DIR, `${targetCI}_landed_cost_card.png`);
			await page.screenshot({ path: lcScreenshotPath });
			fs.copyFileSync(lcScreenshotPath, path.join(ARTIFACT_DIR, `${targetCI}_landed_cost_card.png`));
			console.log(`📸 Landed Cost (UZS) card screenshot saved`);
		}
	}

	await browser.close();
	console.log('\n=== ✅ Real Browser Playwright UAT Finished ===\n');
}

runCiTransportUAT().catch(err => {
	console.error('Fatal error in Playwright UAT:', err);
	process.exit(1);
});
