import { expect, test } from "@playwright/test";

const baseUrl = process.env.E2E_BASE_URL ?? "http://desktop-1bgou2m:5173";

test("Trello-style board visual contract", async ({ page }) => {
  await page.setViewportSize({ width: 1780, height: 900 });
  await page.goto(baseUrl);
  await page.getByLabel("Username").fill(process.env.E2E_MEMBER_USERNAME ?? "");
  await page.getByLabel("Password").fill(process.env.E2E_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("link", { name: process.env.E2E_BOARD_NAME ?? "" }).click();

  await expect(page.locator(".topbar--board")).toBeVisible();
  await expect(page.locator(".trello-inbox")).toBeVisible();
  await expect(page.getByRole("button", { name: /Add another list/ })).toBeVisible();
  await expect(page.locator(".trello-dock")).toBeVisible();

  const geometry = await page.evaluate(() => {
    const inbox = document.querySelector(".trello-inbox")?.getBoundingClientRect();
    const canvas = document.querySelector(".trello-canvas")?.getBoundingClientRect();
    const dock = document.querySelector(".trello-dock")?.getBoundingClientRect();
    const lists = document.querySelectorAll(".trello-list");
    return {
      inboxWidth: inbox?.width ?? 0,
      canvasWidth: canvas?.width ?? 0,
      dockBottom: dock ? window.innerHeight - dock.bottom : -1,
      listCount: lists.length,
      horizontalOverflow:
        (document.querySelector(".trello-board-lists")?.scrollWidth ?? 0) >=
        (document.querySelector(".trello-board-lists")?.clientWidth ?? 0),
      topbarBackground: getComputedStyle(document.querySelector(".topbar")!).backgroundColor,
      canvasBackground: getComputedStyle(document.querySelector(".trello-canvas")!).backgroundImage,
    };
  });

  expect(geometry.inboxWidth).toBeGreaterThanOrEqual(250);
  expect(geometry.inboxWidth).toBeLessThanOrEqual(275);
  expect(geometry.canvasWidth).toBeGreaterThan(1200);
  expect(geometry.dockBottom).toBeGreaterThanOrEqual(5);
  expect(geometry.dockBottom).toBeLessThanOrEqual(20);
  expect(geometry.listCount).toBe(4);
  expect(geometry.horizontalOverflow).toBeTruthy();
  expect(geometry.topbarBackground).not.toBe("rgba(0, 0, 0, 0)");
  expect(geometry.canvasBackground).toContain("linear-gradient");

  await page.screenshot({
    path: "../runtime/setup/trello-ui-qa.png",
    fullPage: true,
  });
});
