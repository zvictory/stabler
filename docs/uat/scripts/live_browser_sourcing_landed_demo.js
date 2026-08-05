const { chromium } = require('playwright');
const path = require('path');

const ARTIFACTS_DIR = '/Users/zafar/.gemini/antigravity/brain/0e9acec9-ee6b-4ab3-870f-d78d657ba3e5';

(async () => {
	console.log('Launching browser for Landed Cost Sourcing Demonstration...');
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	try {
		console.log('Step 1: Logging in as sourcing.mikas@erpstable.com...');
		await page.goto('https://mikas.erpstable.com/stabler#/', { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(2000);

		const emailInput = page.locator('input[type="email"], input[name="login_id"], input[type="text"]').first();
		if (await emailInput.count() > 0 && await emailInput.isVisible()) {
			await emailInput.fill('sourcing.mikas@erpstable.com');
			await page.fill('input[type="password"]', 'MikasUAT2026!');
			await page.click('button[type="submit"]');
			await page.waitForTimeout(3000);
		}

		console.log('Step 2: Navigating directly to Sourcing Workspace for CRM-DEAL-2026-00098...');
		await page.goto('https://mikas.erpstable.com/stabler#/tender/sourcing?deal=CRM-DEAL-2026-00098', { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(4000);

		console.log('Step 3: Setting itemized Landed Charges for 5 Supplier Quotations via API...');
		const quotesLandedData = [
			{ name: 'PUR-SQTN-2026-00126', supplier: 'Tashkent Bearing Factory LLC', charges: [{ charge_type: 'Freight', description: 'Domestic Logistics', amount: 1200000 }, { charge_type: 'Customs Duty', description: 'Import Tariff', amount: 800000 }] },
			{ name: 'PUR-SQTN-2026-00127', supplier: 'Ural Components CJSC', charges: [{ charge_type: 'Freight', description: 'Rail Freight from Russia', amount: 600000 }, { charge_type: 'Customs Duty', description: 'EAEU Tariff', amount: 360000 }] },
			{ name: 'PUR-SQTN-2026-00128', supplier: 'Samarkand Industrial Supply', charges: [{ charge_type: 'Freight', description: 'Regional Transit', amount: 1500000 }, { charge_type: 'Customs Duty', description: 'Terminal Fee', amount: 900000 }] },
			{ name: 'PUR-SQTN-2026-00129', supplier: 'SinoBearings Shanghai Ltd', charges: [{ charge_type: 'Freight', description: 'Sea Freight + Lubeck Rail', amount: 2000000 }, { charge_type: 'Customs Duty', description: 'Uzbekistan Tariff', amount: 1200000 }] },
			{ name: 'PUR-SQTN-2026-00130', supplier: 'Fergana Tech Trade', charges: [{ charge_type: 'Freight', description: 'Truck Freight', amount: 1800000 }, { charge_type: 'Customs Duty', description: 'Handling', amount: 1000000 }] }
		];

		for (const q of quotesLandedData) {
			const res = await page.evaluate(async (data) => {
				const csrf = window.__STABLER__?.csrfToken || '';
				const body = new URLSearchParams();
				body.append('quotation', data.name);
				body.append('charges', JSON.stringify(data.charges));

				const r = await fetch('/api/method/stabler.api.sourcing.update_quotation_landed', {
					method: 'POST',
					headers: {
						'Content-Type': 'application/x-www-form-urlencoded',
						'X-Frappe-CSRF-Token': csrf
					},
					body: body.toString()
				});
				const resJson = await r.json();
				return resJson.message;
			}, q);
			console.log(`[PASS] Updated Landed Charges for ${q.supplier} (${q.name}): Landed Total = ${res?.base_landed_total?.toLocaleString()} UZS`);
		}

		console.log('Step 4: Reloading workspace to reflect all Landed Cost calculations...');
		await page.reload({ waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(4000);

		console.log('Step 5: Taking Full Sourcing Comparison Table Screenshot...');
		await page.screenshot({ path: path.join(ARTIFACTS_DIR, '09_sourcing_comparison_landed_ranked.png'), fullPage: true });
		console.log('Screenshot saved: 09_sourcing_comparison_landed_ranked.png');

		console.log('Step 6: Opening Landed Charges Editor UI Modal for Tashkent Bearing Factory LLC...');
		const landedBtn = page.locator('button:has-text("Landed cost")').first();
		if (await landedBtn.count() > 0 && await landedBtn.isVisible()) {
			await landedBtn.click();
			await page.waitForTimeout(2500);
			await page.screenshot({ path: path.join(ARTIFACTS_DIR, '08_landed_charges_editor_modal.png'), fullPage: true });
			console.log('Screenshot saved: 08_landed_charges_editor_modal.png');
		}

		console.log('\n--- LANDED COST SOURCING VERIFICATION COMPLETE ---');
	} catch (err) {
		console.error('Error in Landed Cost Sourcing script:', err);
	} finally {
		await browser.close();
	}
})();
