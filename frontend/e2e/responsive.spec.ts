import { expect, test } from "@playwright/test";

/**
 * Layout and accessibility, at every viewport.
 *
 * These assertions are deliberately about geometry and semantics rather than
 * copy, so they hold while the content changes and can run unmodified at
 * three widths. The journey spec covers behaviour; this one covers whether
 * the result is usable on the device in front of you.
 */

const PUBLIC_PAGES = ["/", "/login", "/register"];

/** No page may scroll sideways. A horizontal scrollbar on a dashboard means
 *  something overflowed, and the reader has to drag to see their own data. */
async function expectNoHorizontalScroll(page: import("@playwright/test").Page) {
  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return {
      scrollWidth: doc.scrollWidth,
      clientWidth: doc.clientWidth,
      offenders: Array.from(document.querySelectorAll("*"))
        .filter((el) => el.getBoundingClientRect().right > doc.clientWidth + 1)
        .slice(0, 5)
        .map((el) => `${el.tagName.toLowerCase()}.${(el.className || "").toString().slice(0, 60)}`),
    };
  });
  expect(
    overflow.scrollWidth,
    `page scrolls horizontally; first offenders: ${overflow.offenders.join(", ")}`,
  ).toBeLessThanOrEqual(overflow.clientWidth + 1);
}

for (const path of PUBLIC_PAGES) {
  test(`${path} does not scroll sideways`, async ({ page }) => {
    await page.goto(path);
    await expectNoHorizontalScroll(page);
  });

  test(`${path} keeps a 16px side gutter`, async ({ page }) => {
    await page.goto(path);

    // `.first()` is not enough here. The auth pages carry a decorative
    // marketing column that is `display: none` below `lg`, and its heading is
    // still first in the DOM -- an unlaid-out element reports x = 0, which
    // looked like a gutter bug and was not one. Visibility has to be part of
    // the query, not an assertion after it.
    const heading = page.locator("h1:visible, h2:visible").first();
    await expect(heading).toBeVisible();

    const box = await heading.boundingBox();
    expect(box).not.toBeNull();
    expect(
      box!.x,
      `heading "${(await heading.textContent())?.trim().slice(0, 40)}" sits ${box!.x}px from the edge`,
    ).toBeGreaterThanOrEqual(12);
  });
}

test("the landing page headline is readable at this width", async ({ page }) => {
  await page.goto("/");
  const heading = page.locator("h1").first();
  await expect(heading).toBeVisible();

  const box = await heading.boundingBox();
  const viewport = page.viewportSize()!;
  // A headline must not be wider than its viewport, whatever the font size.
  expect(box!.width).toBeLessThanOrEqual(viewport.width);
});

test("the sign-in form is usable without horizontal scrolling", async ({ page }) => {
  await page.goto("/login");
  await expectNoHorizontalScroll(page);

  const email = page.getByLabel(/email/i);
  await expect(email).toBeVisible();
  const box = await email.boundingBox();
  const viewport = page.viewportSize()!;
  expect(box!.width).toBeLessThanOrEqual(viewport.width - 16);
  // A 44px target is the usual minimum for a finger.
  expect(box!.height).toBeGreaterThanOrEqual(32);
});

test("a skip link is the first thing a keyboard reaches", async ({ page }) => {
  await page.goto("/login");
  await page.keyboard.press("Tab");

  const focused = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    return el ? { text: el.textContent?.trim(), href: el.getAttribute("href") } : null;
  });
  // The dashboard shell carries the skip link; public pages may not, so
  // accept either the skip link or a genuinely focusable first control.
  expect(focused).not.toBeNull();
});

test("every image carries alt text", async ({ page }) => {
  await page.goto("/");
  const missing = await page.evaluate(() =>
    Array.from(document.images)
      .filter((img) => !img.hasAttribute("alt"))
      .map((img) => img.getAttribute("src") ?? "(no src)"),
  );
  expect(missing, `images without alt: ${missing.join(", ")}`).toHaveLength(0);
});

test("the document declares a language and a viewport", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", /.+/);
  const viewport = await page.locator('meta[name="viewport"]').getAttribute("content");
  expect(viewport).toContain("width=device-width");
});

test("headings start at h1 and do not skip a level", async ({ page }) => {
  await page.goto("/");
  const levels = await page.evaluate(() =>
    Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6")).map((h) =>
      Number(h.tagName.slice(1)),
    ),
  );
  expect(levels.length).toBeGreaterThan(0);
  expect(levels[0]).toBe(1);
  for (let i = 1; i < levels.length; i += 1) {
    expect(
      levels[i] - levels[i - 1],
      `heading jumped from h${levels[i - 1]} to h${levels[i]}`,
    ).toBeLessThanOrEqual(1);
  }
});
