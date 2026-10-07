import { expect, test, chromium, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

function env(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing E2E environment variable: ${name}`);
  return value;
}

const baseURL = () => process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173";
const monthlyURL = () => process.env.E2E_MONTHLY_URL ?? "http://127.0.0.1:5174";
const boardName = () => env("E2E_BOARD_NAME");

async function login(page: Page, username: string) {
  await page.goto(baseURL());
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(env("E2E_PASSWORD"));
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator(".topbar__user")).toContainText(username);
}

async function loginMonthly(page: Page) {
  await page.goto(monthlyURL());
  await page.getByLabel("Username").fill(env("E2E_MEMBER_USERNAME"));
  await page.getByLabel("Password").fill(env("E2E_PASSWORD"));
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator(".topbar__user")).toContainText(env("E2E_MEMBER_USERNAME"));
}

async function openBoard(page: Page) {
  await page.getByRole("link", { name: boardName() }).click();
  await expect(page.getByRole("heading", { name: boardName() })).toBeVisible();
}

function column(page: Page, state: string) {
  if (state === "BACKLOG") {
    return page.locator('.trello-inbox[data-state="BACKLOG"]');
  }
  return page.locator(`.kanban-column[data-state="${state}"]`);
}

function columnDropArea(page: Page, state: string) {
  return state === "BACKLOG"
    ? column(page, state).locator(".trello-inbox__cards")
    : column(page, state).locator(".kanban-column__body");
}

function card(page: Page, title: string) {
  return page.locator(".task-card").filter({ hasText: title }).first();
}

async function addCard(page: Page, title: string) {
  const input = page.getByLabel("Add a card to Inbox");
  await input.fill(title);
  await page.getByRole("button", { name: "Add card", exact: true }).first().click();
  await expect(column(page, "BACKLOG").locator(".task-card").filter({ hasText: title })).toBeVisible();
}
async function dragCard(
  page: Page,
  title: string,
  targetState: string,
  targetTitle?: string,
  expectSuccess = true,
) {
  const source = card(page, title);
  const target = targetTitle
    ? card(page, targetTitle)
    : columnDropArea(page, targetState);

  await source.scrollIntoViewIfNeeded();
  await target.scrollIntoViewIfNeeded();
  const sourceBox = await source.boundingBox();
  const targetBox = await target.boundingBox();
  if (!sourceBox || !targetBox) throw new Error("Unable to resolve drag coordinates");

  const sx = sourceBox.x + sourceBox.width / 2;
  const sy = sourceBox.y + Math.min(24, sourceBox.height / 2);
  const tx = targetBox.x + targetBox.width / 2;
  const ty = targetTitle
    ? targetBox.y + Math.min(20, targetBox.height / 3)
    : targetBox.y + Math.min(70, targetBox.height / 2);

  await page.mouse.move(sx, sy);
  await page.mouse.down();
  await page.mouse.move(sx + 8, sy + 8, { steps: 3 });
  await page.mouse.move(tx, ty, { steps: 18 });
  await page.mouse.up();

  if (expectSuccess) {
    await expect(column(page, targetState).locator(".task-card").filter({ hasText: title })).toBeVisible();
  }
  await page.waitForTimeout(120);
}

async function editCard(page: Page, currentTitle: string, nextTitle: string) {
  await card(page, currentTitle).getByRole("button").click();
  await page.getByRole("button", { name: "Edit card" }).click();
  await page.getByLabel("Title", { exact: true }).fill(nextTitle);
  await page.getByLabel("Description", { exact: true }).fill("Edited through browser E2E");
  await page.getByRole("button", { name: "Save card details" }).click();
  await expect(page.getByRole("heading", { name: nextTitle })).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();
  await expect(card(page, nextTitle)).toBeVisible();
}

function monitor(page: Page) {
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(`console: ${message.text()}`);
  });
  page.on("requestfailed", (request) => {
    const errorText = request.failure()?.errorText ?? "";
    const expectedReloadAbort =
      request.method() === "GET" &&
      request.url().includes("/api/v1/boards/") &&
      request.url().endsWith("/snapshot") &&
      errorText === "net::ERR_ABORTED";
    if (!expectedReloadAbort) {
      problems.push(`requestfailed: ${request.method()} ${request.url()} ${errorText}`);
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      problems.push(`http ${response.status()}: ${response.request().method()} ${response.url()}`);
    }
  });
  return () => expect(problems, problems.join("\n")).toEqual([]);
}
test("card workflow: create, 10+ moves, reorder, edit, reload, delete", async ({ page }) => {
  await login(page, env("E2E_MEMBER_USERNAME"));
  await openBoard(page);
  const assertClean = monitor(page);

  const main = `Move QA ${Date.now()}`;
  const first = `Order A ${Date.now()}`;
  const second = `Order B ${Date.now()}`;
  await addCard(page, first);
  await addCard(page, second);
  await addCard(page, main);

  const moves = [
    "TODO",
    "IN_PROGRESS",
    "DONE",
    "BLOCKED",
    "IN_PROGRESS",
    "TODO",
    "BACKLOG",
    "TODO",
    "IN_PROGRESS",
    "BLOCKED",
    "DONE",
    "BACKLOG",
  ];
  for (const state of moves) await dragCard(page, main, state);

  await dragCard(page, second, "BACKLOG", first);
  const beforeReload = await column(page, "BACKLOG").locator(".task-card strong").allTextContents();
  expect(beforeReload.indexOf(second)).toBeLessThan(beforeReload.indexOf(first));

  const edited = `${main} edited`;
  await editCard(page, main, edited);
  await page.reload();
  await expect(page.getByRole("heading", { name: boardName() })).toBeVisible();
  const afterReload = await column(page, "BACKLOG").locator(".task-card strong").allTextContents();
  expect(afterReload.indexOf(second)).toBeLessThan(afterReload.indexOf(first));
  await expect(column(page, "BACKLOG").locator(".task-card").filter({ hasText: edited })).toBeVisible();

  await card(page, edited).getByRole("button").click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete card" }).click();
  await expect(card(page, edited)).toHaveCount(0);

  const afterMoves = `Created after moves ${Date.now()}`;
  await addCard(page, afterMoves);
  await expect(card(page, afterMoves)).toBeVisible();
  assertClean();
});
test("multi-tab and two-user sessions remain independent", async ({ browser }) => {
  const contextA = await browser.newContext();
  const tabA = await contextA.newPage();
  await login(tabA, env("E2E_MEMBER_USERNAME"));
  await openBoard(tabA);
  const tabB = await contextA.newPage();
  await tabB.goto(baseURL());
  await tabB.getByRole("link", { name: boardName() }).click();

  const contextB = await browser.newContext();
  const userB = await contextB.newPage();
  await login(userB, env("E2E_MEMBER2_USERNAME"));
  await openBoard(userB);

  const titleA = `Tab A ${Date.now()}`;
  const titleB = `User B ${Date.now()}`;

  await addCard(tabA, titleA);
  await tabB.reload();
  await expect(card(tabB, titleA)).toBeVisible();

  await addCard(userB, titleB);

  await dragCard(tabA, titleA, "TODO", undefined, false);
  await expect(
    tabA.getByText("This board changed while you were moving the card. I reloaded the latest version."),
  ).toBeVisible();
  await dragCard(tabA, titleA, "TODO");

  await dragCard(userB, titleB, "IN_PROGRESS", undefined, false);
  await expect(
    userB.getByText("This board changed while you were moving the card. I reloaded the latest version."),
  ).toBeVisible();
  await dragCard(userB, titleB, "IN_PROGRESS");

  const cleanA = monitor(tabA);
  const cleanB = monitor(userB);

  await tabB.reload();
  await expect(column(tabB, "TODO").locator(".task-card").filter({ hasText: titleA })).toBeVisible();
  await expect(column(tabB, "IN_PROGRESS").locator(".task-card").filter({ hasText: titleB })).toBeVisible();

  await tabB.bringToFront();
  await tabB.waitForTimeout(500);
  await expect(tabB.locator(".topbar__user")).toContainText(env("E2E_MEMBER_USERNAME"));
  await expect(userB.locator(".topbar__user")).toContainText(env("E2E_MEMBER2_USERNAME"));

  cleanA();
  cleanB();
  await contextA.close();
  await contextB.close();
});
test("persistent browser profile survives restart and explicit logout revokes it", async () => {
  const profile = await mkdtemp(path.join(os.tmpdir(), "emega-e2e-"));
  try {
    let context = await chromium.launchPersistentContext(profile, {
      channel: "chrome",
      headless: true,
      viewport: { width: 1920, height: 1080 },
    });
    let page = context.pages()[0] ?? (await context.newPage());
    await login(page, env("E2E_MEMBER2_USERNAME"));
    await openBoard(page);
    await context.close();

    context = await chromium.launchPersistentContext(profile, {
      channel: "chrome",
      headless: true,
      viewport: { width: 1920, height: 1080 },
    });
    page = context.pages()[0] ?? (await context.newPage());
    await page.goto(baseURL());
    await expect(page.locator(".topbar__user")).toContainText(env("E2E_MEMBER2_USERNAME"));
    await openBoard(page);

    const title = `Restart QA ${Date.now()}`;
    await addCard(page, title);
    await dragCard(page, title, "TODO");
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
    await context.close();

    context = await chromium.launchPersistentContext(profile, {
      channel: "chrome",
      headless: true,
      viewport: { width: 1920, height: 1080 },
    });
    page = context.pages()[0] ?? (await context.newPage());
    await page.goto(baseURL());
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
    await context.close();
  } finally {
    await rm(profile, { recursive: true, force: true });
  }
});
test("Productivity and Monthly Evaluation remain authenticated together", async ({ browser }) => {
  const context = await browser.newContext();
  const trello = await context.newPage();
  await login(trello, env("E2E_MEMBER_USERNAME"));
  await openBoard(trello);

  const monthly = await context.newPage();
  await loginMonthly(monthly);

  const cookies = await context.cookies();
  const names = new Set(cookies.map((cookie) => cookie.name));
  expect(names).toContain("emega_productivity_sessionid");
  expect(names).toContain("emega_productivity_csrftoken");
  expect(names).toContain("monthly_evaluation_sessionid");
  expect(names).toContain("monthly_evaluation_csrftoken");
  expect(names).not.toContain("sessionid");

  const host = new URL(baseURL()).hostname;
  const monthlyHost = new URL(monthlyURL()).hostname;
  const productivitySession = cookies.find(
    (cookie) => cookie.name === "emega_productivity_sessionid",
  );
  const productivityCsrf = cookies.find(
    (cookie) => cookie.name === "emega_productivity_csrftoken",
  );
  const monthlySession = cookies.find(
    (cookie) => cookie.name === "monthly_evaluation_sessionid",
  );
  const monthlyCsrf = cookies.find(
    (cookie) => cookie.name === "monthly_evaluation_csrftoken",
  );
  expect(productivitySession).toMatchObject({
    domain: host,
    path: "/",
    httpOnly: true,
    secure: false,
    sameSite: "Lax",
  });
  expect(productivityCsrf).toMatchObject({
    domain: host,
    path: "/",
    httpOnly: false,
    secure: false,
    sameSite: "Lax",
  });
  expect(monthlySession).toMatchObject({
    domain: monthlyHost,
    path: "/",
    httpOnly: true,
    secure: false,
    sameSite: "Lax",
  });
  expect(monthlyCsrf).toMatchObject({
    domain: monthlyHost,
    path: "/",
    httpOnly: false,
    secure: false,
    sameSite: "Lax",
  });

  const cleanTrello = monitor(trello);
  const cleanMonthly = monitor(monthly);
  const title = `Cross app ${Date.now()}`;
  await trello.bringToFront();
  await addCard(trello, title);
  await dragCard(trello, title, "TODO");
  await editCard(trello, title, `${title} edited`);

  await monthly.bringToFront();
  await monthly.getByRole("link", { name: "My Tasks" }).click();
  await expect(monthly.getByRole("heading", { name: "My Tasks" })).toBeVisible();

  for (let i = 0; i < 3; i += 1) {
    await trello.bringToFront();
    await expect(trello.locator(".topbar__user")).toContainText(env("E2E_MEMBER_USERNAME"));
    await monthly.bringToFront();
    await expect(monthly.locator(".topbar__user")).toContainText(env("E2E_MEMBER_USERNAME"));
  }

  await trello.bringToFront();
  await trello.reload();
  await expect(trello.locator(".topbar__user")).toContainText(env("E2E_MEMBER_USERNAME"));
  cleanTrello();
  cleanMonthly();
  await context.close();
});
test("admin-only board creation remains enforced in UI", async ({ browser }) => {
  const memberContext = await browser.newContext();
  const memberPage = await memberContext.newPage();
  await login(memberPage, env("E2E_MEMBER_USERNAME"));
  await expect(memberPage.getByRole("button", { name: "+ Create board" })).toHaveCount(0);

  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await login(adminPage, env("E2E_ADMIN_USERNAME"));
  await expect(adminPage.getByRole("button", { name: "+ Create board" })).toBeVisible();

  await memberContext.close();
  await adminContext.close();
});


test("server-side session-generation revocation invalidates an open browser", async ({ page }) => {
  await login(page, env("E2E_MEMBER2_USERNAME"));
  await expect(page.locator(".topbar__user")).toContainText(env("E2E_MEMBER2_USERNAME"));

  const projectRoot = path.resolve(process.cwd(), "..");
  const python = path.join(projectRoot, ".venv", "Scripts", "python.exe");
  const code = [
    "import os",
    "from accounts.models import User",
    "u=User.objects.get(username=os.environ['E2E_MEMBER2_USERNAME'])",
    "u.session_generation += 1",
    "u.save(update_fields=['session_generation'])",
  ].join("; ");
  execFileSync(
    python,
    ["backend/manage.py", "shell", "-c", code],
    { cwd: projectRoot, env: process.env, stdio: "pipe" },
  );

  await page.reload();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});


test("custom list UI: color, archive cards, archive list", async ({ page }) => {
  await login(page, env("E2E_MEMBER_USERNAME"));
  await openBoard(page);
  const assertClean = monitor(page);

  const listName = `Waiting ${Date.now()}`;
  const cardTitle = `Custom list card ${Date.now()}`;

  await page.getByRole("button", { name: /Add another list/ }).click();
  await page.getByLabel("New list title").fill(listName);
  await page.getByRole("button", { name: "Add list" }).click();

  let customList = page
    .locator(".trello-list")
    .filter({ has: page.getByRole("heading", { name: listName, exact: true }) });
  await expect(customList).toBeVisible();

  await customList.getByRole("button", { name: `List actions for ${listName}` }).click();
  await expect(page.locator(".trello-list-menu--floating")).toHaveCount(1);
  const menuBounds = await page.locator(".trello-list-menu--floating").boundingBox();
  expect(menuBounds).not.toBeNull();
  expect(menuBounds!.x).toBeGreaterThanOrEqual(0);
  expect(menuBounds!.y).toBeGreaterThanOrEqual(0);
  expect(menuBounds!.x + menuBounds!.width).toBeLessThanOrEqual(1920);
  expect(menuBounds!.y + menuBounds!.height).toBeLessThanOrEqual(1080);

  const todoList = page
    .locator(".trello-list")
    .filter({ has: page.getByRole("heading", { name: "To Do", exact: true }) });
  await todoList.getByRole("button", { name: "List actions for To Do" }).click();
  await expect(page.locator(".trello-list-menu--floating")).toHaveCount(1);
  await expect(customList.getByRole("button", { name: `List actions for ${listName}` })).toBeVisible();

  await customList.getByRole("button", { name: `List actions for ${listName}` }).click();
  await expect(page.getByRole("button", { name: "Rename list" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Delete list" })).toHaveCount(0);
  await page.getByRole("button", { name: "Navy deep" }).click();
  await expect(customList).toHaveAttribute("data-color", "navy2");

  await page.getByRole("button", { name: "Change text color" }).click();
  await page.getByRole("button", { name: "White text" }).click();
  await expect(customList).toHaveAttribute("data-text-color", "white");

  await page.reload();
  customList = page
    .locator(".trello-list")
    .filter({ has: page.getByRole("heading", { name: listName, exact: true }) });
  await expect(customList).toHaveAttribute("data-color", "navy2");
  await expect(customList).toHaveAttribute("data-text-color", "white");

  await customList.getByRole("button", { name: "Add a card" }).click();
  await page.getByLabel(`Add a card to ${listName}`).fill(cardTitle);
  await customList.getByRole("button", { name: "Add card", exact: true }).click();
  await expect(customList.locator(".task-card").filter({ hasText: cardTitle })).toBeVisible();

  await customList.getByRole("button", { name: `List actions for ${listName}` }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Archive all cards in this list" }).click();
  await expect(customList.locator(".task-card").filter({ hasText: cardTitle })).toHaveCount(0);
  await expect(customList).toBeVisible();

  await customList.getByRole("button", { name: `List actions for ${listName}` }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Archive this list" }).click();
  await expect(page.getByRole("heading", { name: listName, exact: true })).toHaveCount(0);

  assertClean();
});


test("admin can rename board inline and the name persists", async ({ page }) => {
  await login(page, env("E2E_ADMIN_USERNAME"));
  await openBoard(page);
  const assertClean = monitor(page);

  const originalName = boardName();
  const renamed = `${originalName} Renamed ${Date.now()}`;

  await page.getByRole("button", { name: "Edit board name" }).click();
  await page.getByRole("textbox", { name: "Board name", exact: true }).fill(renamed);
  await page.getByRole("button", { name: "Save board name" }).click();
  await expect(page.getByRole("heading", { name: renamed, exact: true })).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { name: renamed, exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Edit board name" }).click();
  await page.getByRole("textbox", { name: "Board name", exact: true }).fill(originalName);
  await page.getByRole("button", { name: "Save board name" }).click();
  await expect(page.getByRole("heading", { name: originalName, exact: true })).toBeVisible();

  assertClean();
});


test("card detail modal keeps dark readable text on its light background", async ({ page }) => {
  await login(page, env("E2E_MEMBER_USERNAME"));
  await openBoard(page);
  const assertClean = monitor(page);

  const title = `Modal contrast ${Date.now()}`;
  await addCard(page, title);
  await card(page, title).getByRole("button").click();

  const modal = page.getByRole("dialog", { name: title });
  await expect(modal).toBeVisible();

  const modalColors = await modal.evaluate((element) => {
    const root = getComputedStyle(element);
    const heading = element.querySelector("h2");
    const value = element.querySelector(".detail-grid dd");
    const sectionHeading = Array.from(element.querySelectorAll("h3"))
      .find((node) => node.textContent?.includes("Card details"));
    return {
      background: root.backgroundColor,
      color: root.color,
      headingColor: heading ? getComputedStyle(heading).color : "",
      valueColor: value ? getComputedStyle(value).color : "",
      sectionHeadingColor: sectionHeading ? getComputedStyle(sectionHeading).color : "",
    };
  });

  expect(modalColors.background).toBe("rgb(255, 255, 255)");
  expect(modalColors.color).toBe("rgb(23, 32, 51)");
  expect(modalColors.headingColor).toBe("rgb(23, 32, 51)");
  expect(modalColors.valueColor).toBe("rgb(23, 32, 51)");
  expect(modalColors.sectionHeadingColor).toBe("rgb(23, 32, 51)");

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete card" }).click();
  await expect(card(page, title)).toHaveCount(0);

  assertClean();
});
