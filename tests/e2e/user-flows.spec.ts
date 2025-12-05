import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const fixtureImage = path.join(__dirname, '..', 'fixtures', 'lesion.png');

const dermResponse = {
  agent: 'dermatologist',
  title: 'Dermatology Attending Physician',
  result: {},
  verification: {
    answer: 'Likely eczema flare; keep it gentle, avoid irritants.',
    provisional_diagnosis: 'eczema',
    differentials: ['contact dermatitis', 'tinea corporis'],
    followups: ['Does it ooze or crust?', 'Any new soap/detergent?', 'Immunosuppression?', 'Fever?'],
    plan: 'Moisturize, avoid triggers, consider OTC hydrocortisone, see derm if no improvement in 48h.',
    triage: 'Seek urgent care for fever, pain, rapidly spreading rash, mucosal involvement.',
    risk_flags: 'No red flags provided.',
    confidence: '0.62',
  },
  meta: { model: 'stub', verifier: 'stub' },
};

const therapistResponse = {
  agent: 'therapist',
  title: 'Generalist Therapist',
  result: {},
  verification: {
    answer: 'Sounds overwhelming. Let’s slow down and create one small next step.',
    provisional_diagnosis: 'stress response',
    differentials: ['anxiety', 'adjustment'],
    followups: ['Safety check: thoughts of self-harm?', 'Sleep quality?', 'Caffeine/alcohol use?'],
    plan: 'Box breathing 4-4-6, hydrate, short walk, text a trusted person.',
    triage: 'If self-harm urges appear, contact local crisis line or ER immediately.',
    risk_flags: 'No explicit risk disclosed; monitor mood swings.',
    confidence: '0.55',
  },
  meta: { model: 'stub', verifier: 'stub' },
};

test.describe('DoctorAI web UI', () => {
  test('dermatology flow with follow-up gating and screenshot', async ({ page }) => {
    let callCount = 0;
    await page.route('**/analyze', async (route) => {
      callCount += 1;
      await page.waitForTimeout(callCount === 1 ? 220 : 120);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(dermResponse),
      });
    });

    await page.goto('/');
    await page.fill('#question', 'Red itchy patch on left forearm for 3 days, no fever.');
    await page.setInputFiles('#image', fixtureImage);

    const status = page.locator('#status');
    const result = page.locator('#resultBody');
    const t0 = Date.now();

    await page.click('#submitBtn');
    await expect(status).toContainText(/Analyzing|Done/);
    await expect(result).toContainText('Plan locked', { timeout: 3000 });

    const followupChip = page.locator('#chatLog .chip').first();
    await followupChip.click();
    await page.click('#submitBtn');

    await expect(result).toContainText('eczema', { timeout: 5000 });
    await expect(result).toContainText('hydrocortisone');
    const followups = result.locator('div.panel').filter({ hasText: 'Follow-up questions' }).locator('li');
    expect(await followups.count()).toBeGreaterThan(2);
    const latencyMs = Date.now() - t0;
    expect(latencyMs).toBeLessThan(4000);

    const shotPath = test.info().outputPath('derm-flow.png');
    await page.screenshot({ path: shotPath, fullPage: true, animations: 'disabled' });
    expect(fs.existsSync(shotPath)).toBeTruthy();
  });

  test('therapist flow resists script injection and keeps followups prominent', async ({ page }) => {
    page.on('dialog', async (dialog) => {
      await dialog.dismiss();
      throw new Error(`Unexpected dialog: ${dialog.message()}`);
    });

    await page.route('**/analyze', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(therapistResponse),
      });
    });

    await page.goto('/');
    await page.getByRole('button', { name: /Therapist/ }).click();
    await page.fill('#question', '<script>alert(1)</script> feeling overwhelmed at work');
    await page.click('#submitBtn');

    const result = page.locator('#resultBody');
    await expect(result).toContainText('Plan locked', { timeout: 3000 });
    await expect(result).toContainText('Box breathing', { timeout: 5000 });
    const followupItems = result.locator('div.panel').filter({ hasText: 'Follow-up questions' }).locator('li');
    const texts = await followupItems.allTextContents();
    expect(texts.join(' ')).toContain('Safety check');
    expect(texts.join(' ')).toContain('Sleep quality');

    const lastUserBubble = page.locator('.bubble.user').last();
    await expect(lastUserBubble).toContainText('<script>alert(1)</script>');
  });

  test('status label updates under slower responses', async ({ page }) => {
    await page.route('**/analyze', async (route) => {
      await page.waitForTimeout(900);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(dermResponse),
      });
    });

    await page.goto('/');
    await page.fill('#question', 'Slow path check');
    await page.click('#submitBtn');

    const status = page.locator('#status');
    await expect(status).toContainText(/Analyzing/);
    await expect(status).toContainText(/Done/, { timeout: 5000 });
  });
});
