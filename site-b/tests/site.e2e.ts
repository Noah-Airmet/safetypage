import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

const q = (s: string) => encodeURIComponent(s);
const PAGE6 = '/d/arxiv/2305.15324/v2/p6';

test.describe('reader', () => {
  test('opens at the page with the quoted passage highlighted', async ({ page }) => {
    await page.goto(`${PAGE6}?q=${q('not the only tool available for AI risk assessment')}`);
    await expect(page.locator('[data-qstatus] .state')).toHaveText('On p. 6');
    await expect(page.locator('#p6 .hl')).toHaveCount(1);
    await expect(page.locator('#p6 .hl')).toBeInViewport();
    await expect(page.locator('[data-goto] input')).toHaveValue('6');
  });

  test('has a selectable text layer that matches the page text', async ({ page }) => {
    await page.goto(PAGE6);
    const words = page.locator('#p6 [data-textlayer] span');
    await expect(words.first()).toHaveText(/Model/);
    expect(await words.count()).toBeGreaterThan(300);
    const box = await words.nth(40).boundingBox();
    const sheet = await page.locator('#p6').boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(sheet!.x);
    expect(box!.x + box!.width).toBeLessThanOrEqual(sheet!.x + sheet!.width + 1);
  });

  test('goes to a page and keeps the address on the page in view', async ({ page }) => {
    await page.goto(PAGE6);
    await page.locator('[data-goto] input').fill('12');
    await page.locator('[data-goto] input').press('Enter');
    await expect(page).toHaveURL(/\/v2\/p12$/);
  });

  test('says when the words are not on the cited page, and where they are', async ({ page }) => {
    await page.goto(`/d/arxiv/2305.15324/v2/p3?q=${q('one of the main tools we have for AI risk assessment')}`);
    await expect(page.locator('[data-qstatus] .state')).toHaveText('Not on p. 3');
    await expect(page.locator('[data-qstatus] a', { hasText: 'It is on p. 6' })).toHaveAttribute('href', /\/v2\/p6\?q=/);
    await expect(page.locator('.hl')).toHaveCount(0);
  });

  test('re-sets an HTML document with block anchors and marks the quote', async ({ page }) => {
    await page.goto(`/d/distill/zoom-in/r1/b21?q=${q('Features are the fundamental unit of neural networks')}`);
    await expect(page.locator('#b21 mark')).toHaveText('Features are the fundamental unit of neural networks');
    await expect(page.locator('#b21 .gutter')).toHaveAttribute('href', '/d/distill/zoom-in/r1/b21');
  });

  test('a link-only page shows the record and opens the source at the page', async ({ page }) => {
    await page.goto('/d/example/link-only-eval-report/r1/p2');
    await expect(page.locator('.sourcecard .btn-primary')).toHaveAttribute('href', /#page=2$/);
    await expect(page.locator('.sheet')).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText('restricted');
  });
});

test('reader: one shell serves every page; a range opens at its first page; a page that is not there says so', async ({ page }) => {
  await page.goto('/d/arxiv/2305.15324/v2/p6-p7');
  await expect(page.locator('#p6')).toBeInViewport();
  await expect(page).toHaveTitle(/Shevlane et al\. 2023, p\. 6/);
  await page.goto('/d/arxiv/2305.15324/v2/p41');
  await expect(page.locator('[data-reader]')).toContainText('There is no p. 41. This version has 20 pages.');
  await page.goto('/d/arxiv/0000.00000/v1/p1');
  await expect(page.locator('[data-reader]')).toContainText('not in the library');
});

test('a link-only page checks a quote against the library\'s copy', async ({ page }) => {
  await page.goto('/d/example/link-only-eval-report/r1/p2');
  await expect(page.locator('[data-excerpt]')).not.toBeEmpty();
  const words = (await page.locator('[data-excerpt]').innerText()).replace(/…/g, '').trim().split(/\s+/).slice(0, 6).join(' ');
  await page.locator('[data-quotecheck] input').fill(words);
  await page.locator('[data-quotecheck] button').click();
  await expect(page.locator('[data-result] .state')).toHaveText('On p. 2');
  await page.locator('[data-quotecheck] input').fill('words that are certainly not anywhere on this page at all');
  await page.locator('[data-quotecheck] button').click();
  await expect(page.locator('[data-result] .state')).toHaveText('Not on p. 2');
});

test('record: the latest version\'s address is the record page', async ({ page }) => {
  await page.goto('/d/arxiv/2305.15324/v2');
  await expect(page.locator('h1')).toHaveText('Model evaluation for extreme risks');
});

test('library: a shelf filters its catalogue without leaving the page', async ({ page }) => {
  await page.goto('/library');
  await page.locator('.shelves .shelf').first().click();
  await expect(page).toHaveURL(/\/library\/[\w-]+$/);
  const rows = page.locator('[data-rows] > a');
  const all = await rows.count();
  expect(all).toBeGreaterThan(0);
  const title = (await rows.first().locator('.name').innerText()).split(' ').slice(0, 2).join(' ');
  await page.locator('[data-filters] input[name="q"]').fill(title);
  await expect(page).toHaveURL(/\?q=/);
  await expect(rows.first().locator('.name')).toContainText(title);
  await page.locator('[data-filters] input[name="q"]').fill('zzzz no such title');
  await expect(rows).toHaveCount(0);
  await expect(page.locator('[data-count]')).toHaveText('0 documents, newest first');
});

test('follow: a topic page is a saved search, and says so when no card mentions it', async ({ page }) => {
  await page.goto('/follow');
  await page.locator('.rows a').first().click();
  await expect(page.locator('h1')).toHaveText('Sabotage');
  await expect(page.locator('.facts a')).toHaveAttribute('href', /\/search\?query=sabotage/);
});

test('landing: the rejected citation is struck through and shows the word that was dropped', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('[data-pane="verified"] .hl')).toBeVisible();
  const rejected = page.locator('.chip[data-state="rejected"]');
  await expect(rejected.locator('.chip-label')).toHaveCSS('text-decoration-line', 'line-through');
  await rejected.click();
  await expect(page.locator('[data-pane="rejected"] .hl[data-kind="reject"]').first()).toBeVisible();
  await expect(page.locator('ins.diff')).toHaveText('not');
});

test('search: results are citations that open the page', async ({ page }) => {
  await page.goto(`/search?query=${q('"risk assessment" evaluation')}`);
  const first = page.locator('.results ol > li > a').first();
  await expect(first).toHaveAttribute('href', /^\/d\/arxiv\/2305\.15324\/v2\/p6/);
  await expect(first.locator('mark').first()).toBeVisible();
});

test('checker: marks each citation Verified, Page only or Rejected, with the reason', async ({ page }) => {
  await page.goto('/check');
  await page.getByRole('button', { name: 'Try an example' }).click();
  await expect(page.locator('.summary')).toHaveText(/1 verified.*1 page only.*3 rejected/);
  await expect(page.locator('.findings > li')).toHaveCount(5);
  await expect(page.locator('.findings')).toContainText('The words are on p. 6');
  await expect(page.locator('.findings ins.diff')).toHaveText('not');
  await expect(page.locator('.findings')).toContainText('there is no p41');
  await expect(page.locator('.checker .hl[data-kind="reject"]').first()).toBeVisible();
});

// A real CitationBench run: three verified citations, one rejected, one page-only.
const TRACE = '/r/cc-sonnet-5-5-43677d-pc-7abbdba8ab.1';

test('replay: a link opens at its step, with the rejection struck through', async ({ page }) => {
  await page.goto(`${TRACE}?step=14`);
  const rejected = page.locator('.rp-answer .chip[data-state="rejected"]');
  await expect(rejected).toHaveCount(1);
  await expect(rejected.locator('.chip-label')).toHaveCSS('text-decoration-line', 'line-through');
  await expect(page.locator('.rp-trace li[aria-current]')).toContainText('Rejected');
  await expect(page.locator('.rp-tally')).toHaveText(/3.*0.*1/);
  await page.locator('.rp-track input').focus();
  await page.keyboard.press('End');
  await expect(page.locator('.rp-answer .chip')).toHaveCount(5);
  await expect(page.locator('.rp-tally')).toHaveText(/3.*1.*1/);
  await page.locator('.rp-answer .chip[data-state="verified"]').first().click();
  await expect(page.locator('.rp-page .hl, .rp-page mark').first()).toBeVisible();
  await page.locator('.rp-track input').focus();
  await page.keyboard.press('Home');
  await expect(page.locator('.rp-answer .chip')).toHaveCount(0);
});

test('leaderboard: a number leads to the run, the run to the replay, the replay to the page', async ({ page }) => {
  await page.goto('/citationbench');
  await page.locator('.board tbody tr').first().locator('td.num a').first().click();
  await expect(page).toHaveURL(/\/citationbench\/runs\/[\w.-]+/);
  await page.locator('.rows a').first().click();
  await expect(page).toHaveURL(/\/r\/[\w.-]+/);
  await page.locator('.rp-track input').focus();
  await page.keyboard.press('End');
  await page.locator('.rp-caption a').click();
  await expect(page).toHaveURL(/\/d\//);
});

const SCREENS = ['/', '/library', '/library/evals', '/follow', '/follow/sabotage', '/d/arxiv/2305.15324', PAGE6, '/d/distill/zoom-in/r1/b21', '/d/example/link-only-eval-report/r1/p2',
  '/search?query=evaluation', '/check?example=1', `${TRACE}?step=14`, '/citationbench', '/citationbench/runs/cc-sonnet-5-5-43677d', '/connect', '/about'];

// One theme: the site is light only.
test.describe('accessibility', () => {
  for (const path of SCREENS) {
    test(path, async ({ page }) => {
      await page.goto(path, { waitUntil: 'networkidle' });
      const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
      expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).slice(0, 4).join(' | ')}`)).toEqual([]);
    });
  }
});

test.describe('accessibility, phone width', () => {
  test.use({ viewport: { width: 390, height: 844 } });
  for (const path of SCREENS) {
    test(path, async ({ page }) => {
      await page.goto(path, { waitUntil: 'networkidle' });
      const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
      expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).slice(0, 4).join(' | ')}`)).toEqual([]);
    });
  }
});

test.describe('phone width', () => {
  test.use({ viewport: { width: 390, height: 844 } });
  for (const path of SCREENS) {
    test(`no sideways scroll: ${path}`, async ({ page }) => {
      await page.goto(path, { waitUntil: 'networkidle' });
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    });
  }
});
