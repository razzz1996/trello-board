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
const monthlyURL = () => {
  if (process.env.E2E_MONTHLY_URL) return process.env.E2E_MONTHLY_URL;
  const base = new URL(baseURL());
  return `${base.protocol}//${base.hostname}:5174`;
};
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

  await page.getByRole("button", { name: "More board actions" }).click();
  await page.getByRole("dialog", { name: "Menu" }).getByText("Archived items", { exact: true }).click();
  const archivedLists = page.getByRole("dialog", { name: "Archived items" });
  await archivedLists.getByRole("button", { name: "Lists", exact: true }).click();
  const archivedList = archivedLists.locator(".trello-archive-item").filter({ hasText: listName });
  await expect(archivedList).toBeVisible();
  await archivedList.getByRole("button", { name: "Restore" }).click();
  await expect(page.getByRole("heading", { name: listName, exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Close board menu" }).click();

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


test("board menu: background, labels, activity, archive restore, and private visibility", async ({ page }) => {
  await login(page, env("E2E_ADMIN_USERNAME"));
  await openBoard(page);
  const assertClean = monitor(page);

  const title = `Menu feature ${Date.now()}`;
  const labelName = `QA ${Date.now()}`;
  const addInput = page.getByLabel("Add a card to Inbox");
  await addInput.fill(title);
  const [snapshotResponse, createResponse] = await Promise.all([
    page.waitForResponse((response) =>
      response.url().endsWith("/snapshot") &&
      response.request().method() === "GET" &&
      response.status() !== 304
    ),
    page.waitForResponse((response) =>
      response.url().includes("/api/v1/tasks") &&
      response.request().method() === "POST"
    ),
    page.getByRole("button", { name: "Add card", exact: true }).first().click(),
  ]);
  expect(
    createResponse.status(),
    `Create card failed: ${await createResponse.text()}`,
  ).toBe(201);
  expect(
    snapshotResponse.status(),
    `Snapshot refresh failed: ${await snapshotResponse.text()}`,
  ).toBe(200);
  await expect(card(page, title)).toBeVisible();

  await page.getByRole("button", { name: "More board actions" }).click();
  const menu = page.getByRole("dialog", { name: "Menu" });
  await expect(menu).toBeVisible();
  await expect(menu.getByText("Visibility: Private")).toBeVisible();
  await expect(menu.getByText("Settings")).toBeVisible();
  await expect(menu.getByText("Change background")).toBeVisible();
  await expect(menu.getByText("Labels", { exact: true })).toBeVisible();
  await expect(menu.getByText("Activity", { exact: true })).toBeVisible();
  await expect(menu.getByText("Archived items", { exact: true })).toBeVisible();
  for (const kind of ["settings", "background", "labels", "activity", "archive"]) {
    await expect(menu.locator(`[data-menu-icon="${kind}"]`)).toHaveCount(1);
  }

  await menu.getByText("Change background").click();
  await page.getByRole("dialog", { name: "Change background" }).getByText("Colors").click();
  await page.getByRole("button", { name: "Deep navy" }).click();
  await expect(page.locator(".trello-canvas")).toHaveCSS("background-image", /linear-gradient/);

  await page.getByRole("button", { name: "Back", exact: true }).click();
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await page.getByRole("dialog", { name: "Menu" }).getByText("Change background").click();
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6WQAAAABJRU5ErkJggg==",
    "base64",
  );
  await page.locator(".trello-hidden-file-input").setInputFiles({
    name: "board-background.png",
    mimeType: "image/png",
    buffer: png,
  });
  await expect(page.locator(".trello-canvas")).toHaveCSS("background-image", /url\(/);

  await page.getByRole("button", { name: "Back", exact: true }).click();
  await page.getByRole("dialog", { name: "Menu" }).getByText("Labels", { exact: true }).click();
  const labelsDialog = page.getByRole("dialog", { name: "Labels" });
  await labelsDialog.getByRole("button", { name: "Edit green label" }).click();
  await labelsDialog.getByLabel("Label name").fill(labelName);
  await labelsDialog.getByLabel("Description / meaning").fill("Ready for quality review");
  await labelsDialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(labelsDialog.getByText(labelName)).toBeVisible();
  await page.getByRole("button", { name: "Close board menu" }).click();

  await card(page, title).getByRole("button").click();
  await page.getByLabel(labelName).click();
  await expect(page.getByLabel(labelName)).toBeChecked();
  await expect(page.getByRole("dialog", { name: title }).getByText(labelName)).toBeVisible();
  await page.getByPlaceholder("Add a comment…").fill("Board menu activity check");
  await page.getByRole("button", { name: "Add comment" }).click();
  await page.getByRole("button", { name: "Close" }).click();
  await expect(card(page, title).getByText(labelName)).toBeVisible();
  await dragCard(page, title, "DONE");

  await page.getByRole("button", { name: "More board actions" }).click();
  await page.getByRole("dialog", { name: "Menu" }).getByText("Activity", { exact: true }).click();
  const activityDialog = page.getByRole("dialog", { name: "Activity" });
  await expect(activityDialog.getByText("Showing board activity from the past 14 days.")).toBeVisible();
  await expect(activityDialog.getByText(new RegExp(`commented on ${title}`))).toBeVisible();
  await expect(activityDialog.getByText(new RegExp(`marked ${title} complete`))).toBeVisible();
  await page.getByRole("button", { name: "Close board menu" }).click();

  await card(page, title).getByRole("button").click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Archive card" }).click();
  await expect(card(page, title)).toHaveCount(0);

  await page.getByRole("button", { name: "More board actions" }).click();
  await page.getByRole("dialog", { name: "Menu" }).getByText("Archived items", { exact: true }).click();
  const archiveDialog = page.getByRole("dialog", { name: "Archived items" });
  const archivedItem = archiveDialog.locator(".trello-archive-item").filter({ hasText: title });
  await expect(archivedItem).toBeVisible();
  await archivedItem.getByRole("button", { name: "Restore" }).click();
  await expect(card(page, title)).toBeVisible();

  await page.getByRole("button", { name: "Close board menu" }).click();
  await card(page, title).getByRole("button").click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete card" }).click();
  await expect(card(page, title)).toHaveCount(0);

  assertClean();
});


test("Version 2 board survives a stale Version 1 snapshot without white-screening", async ({ page }) => {
  await login(page, env("E2E_MEMBER_USERNAME"));
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(error.message));

  await page.route("**/api/v1/boards/*/snapshot", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    delete body.labels;
    if (body.board) {
      delete body.board.background_key;
      delete body.board.background_image_url;
    }
    for (const column of body.columns ?? []) {
      for (const task of column.tasks ?? []) {
        delete task.labels;
      }
    }
    await route.fulfill({ response, json: body });
  });

  await openBoard(page);
  const title = `Stale snapshot ${Date.now()}`;
  await addCard(page, title);
  await expect(card(page, title)).toBeVisible();
  await expect(page.locator(".trello-board-page")).toBeVisible();
  expect(problems, problems.join("\n")).toEqual([]);
});


test("Version 2 board views switch, persist, and show live board presence", async ({ page }) => {
  await login(page, env("E2E_MEMBER_USERNAME"));
  await openBoard(page);
  const assertClean = monitor(page);

  await expect(page.getByRole("button", { name: "Board menu" })).toHaveCount(0);
  const viewButton = page.getByRole("button", { name: "Change board view" });
  await expect(viewButton).toBeVisible();

  await viewButton.click();
  const views = page.getByRole("menu", { name: "Board views" });
  for (const label of ["Board", "Table", "Calendar", "Dashboard", "Timeline"]) {
    await expect(views.getByRole("menuitem", { name: new RegExp(label) })).toBeVisible();
  }

  await views.getByRole("menuitem", { name: /Table/ }).click();
  await expect(page.getByRole("region", { name: "Table view" })).toBeVisible();
  await expect(page).toHaveURL(/view=table/);
  await page.reload();
  await expect(page.getByRole("region", { name: "Table view" })).toBeVisible();

  await page.getByRole("button", { name: "Change board view" }).click();
  await page.getByRole("menuitem", { name: /Calendar/ }).click();
  await expect(page.getByRole("region", { name: "Calendar view" })).toBeVisible();

  await page.getByRole("button", { name: "Change board view" }).click();
  await page.getByRole("menuitem", { name: /Dashboard/ }).click();
  await expect(page.getByRole("region", { name: "Dashboard view" })).toBeVisible();
  await expect(page.getByText("Cards per list")).toBeVisible();
  await expect(page.getByText("Cards per due date")).toBeVisible();
  await expect(page.getByText("Cards per member")).toBeVisible();
  await expect(page.getByText("Cards per label")).toBeVisible();

  await page.getByRole("button", { name: "Change board view" }).click();
  await page.getByRole("menuitem", { name: /Timeline/ }).click();
  await expect(page.getByRole("region", { name: "Timeline view" })).toBeVisible();

  await page.getByRole("button", { name: "Change board view" }).click();
  await page.getByRole("menuitem", { name: /Board/ }).click();
  await expect(page.locator(".trello-board-lists")).toBeVisible();

  const secondBrowser = await chromium.launch();
  try {
    const secondContext = await secondBrowser.newContext({ baseURL: baseURL() });
    const secondPage = await secondContext.newPage();
    await login(secondPage, env("E2E_ADMIN_USERNAME"));
    await openBoard(secondPage);
    await page.bringToFront();
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    const presenceStack = page.locator(".trello-presence-stack");
    await expect(presenceStack).toContainText("", { timeout: 5000 });
    await expect
      .poll(async () => page.locator(".trello-presence-avatar").count(), { timeout: 5000 })
      .toBeGreaterThanOrEqual(2);
    const presenceTitles = await page.locator(".trello-presence-avatar").evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("title") ?? ""),
    );
    expect(presenceTitles.some((title) => title.includes(env("E2E_MEMBER_USERNAME")))).toBeTruthy();
    expect(presenceTitles.some((title) => title.includes(env("E2E_ADMIN_USERNAME")))).toBeTruthy();
    await secondContext.close();
  } finally {
    await secondBrowser.close();
  }

  assertClean();
});


test("Version 2 Trello-style view icons and Timeline dropdown behavior", async ({ page }) => {
  await login(page, env("E2E_MEMBER_USERNAME"));
  await openBoard(page);
  const assertClean = monitor(page);

  await page.getByRole("button", { name: "Change board view" }).click();
  const views = page.getByRole("menu", { name: "Board views" });
  await expect(views.getByRole("menuitem")).toHaveCount(5);
  await expect(views.getByText("Map", { exact: true })).toHaveCount(0);
  await expect(views.locator("svg")).toHaveCount(5);
  await views.getByRole("menuitem", { name: /Timeline/ }).click();

  const timeline = page.getByRole("region", { name: "Timeline view" });
  await expect(timeline).toBeVisible();

  const scale = timeline.getByRole("button", { name: "Timeline scale" });
  await expect(scale).toHaveText(/Week/);

  for (const option of ["Day", "Week", "Month", "Quarter", "Year"]) {
    await scale.click();
    await timeline.getByRole("menuitemradio", { name: option, exact: true }).click();
    await expect(scale).toHaveText(new RegExp(option));
    await expect(
      timeline.locator(`.trello-timeline-grid--${option.toLowerCase()}`),
    ).toBeVisible();
  }

  const grouping = timeline.getByRole("button", { name: "Timeline grouping" });
  await expect(grouping).toHaveText(/List/);

  await grouping.click();
  await timeline.getByRole("menuitemradio", { name: "Member", exact: true }).click();
  await expect(grouping).toHaveText(/Member/);
  await expect(timeline.getByText("No members", { exact: true })).toBeVisible();

  await grouping.click();
  await timeline.getByRole("menuitemradio", { name: "Label", exact: true }).click();
  await expect(grouping).toHaveText(/Label/);
  await expect(timeline.getByText("No labels", { exact: true })).toBeVisible();

  await grouping.click();
  await timeline.getByRole("menuitemradio", { name: "None", exact: true }).click();
  await expect(grouping).toHaveText(/None/);
  await expect(timeline.locator(".trello-timeline-grid.is-ungrouped")).toBeVisible();

  await timeline.getByRole("button", { name: "Close timeline view" }).click();
  await expect(page.locator(".trello-board-lists")).toBeVisible();

  assertClean();
});


test("Version 2 Planner is a functional weekly agenda with Trello-style due filters", async ({ page }) => {
  await login(page, env("E2E_MEMBER_USERNAME"));
  await openBoard(page);
  const assertClean = monitor(page);

  const boardMatch = page.url().match(/\/boards\/([^?]+)/);
  expect(boardMatch).not.toBeNull();
  const boardId = boardMatch?.[1] ?? "";
  const sessionUser = await page.evaluate(async () => {
    const response = await fetch("/api/v1/session/me/");
    return response.json();
  });

  const due = new Date();
  due.setHours(due.getHours() + 2, 0, 0, 0);
  const fakeTask = {
    id: "00000000-0000-4000-8000-000000000099",
    board_id: boardId,
    column_id: "00000000-0000-4000-8000-000000000088",
    column_state: "TODO",
    column_name: "To Do",
    title: "Planner assigned agenda item",
    description: "",
    priority: 2,
    current_owner_id: sessionUser.id,
    original_owner_id: sessionUser.id,
    row_version: 1,
    position: 0,
    draft_due_at: due.toISOString(),
    draft_acceptance_criteria: "",
    recurrence_frequency: "NONE",
    recurrence_next_at: null,
    recurrence_last_triggered_at: null,
    recurrence_generation: 0,
    committed_at: null,
    current_commitment: null,
    is_cancelled: false,
    is_archived: false,
    archived_at: null,
    cancelled_at: null,
    cancelled_reason: "",
    checklist_items: [],
    comments: [],
    change_proposals: [],
    submissions: [],
    labels: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  await page.route("**/api/v1/tasks", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([fakeTask]) });
      return;
    }
    await route.continue();
  });

  const canvas = page.locator(".trello-canvas");
  const before = await canvas.boundingBox();
  expect(before).not.toBeNull();

  await page.locator(".trello-dock button").filter({ hasText: "Planner" }).click();
  const planner = page.getByRole("complementary", { name: "Planner" });
  await expect(planner).toBeVisible();
  await expect(page.locator(".trello-workspace")).toHaveClass(/trello-workspace--planner/);
  await expect(planner.getByText("Connect your calendar account")).toHaveCount(0);

  const after = await canvas.boundingBox();
  expect(after).not.toBeNull();
  expect(after!.x).toBeGreaterThan(before!.x);
  expect(after!.width).toBeLessThan(before!.width);

  const toolbarButtons = planner.locator(".trello-planner-toolbar button");
  await expect(toolbarButtons).toHaveCount(5);
  await expect(planner.getByText("Planner assigned agenda item")).toBeVisible();

  await planner.getByRole("button", { name: "Previous day" }).click();
  await expect(planner.locator(".trello-planner-day h3").first()).toContainText("Yesterday");
  await planner.getByRole("button", { name: "Next day" }).click();
  await expect(planner.locator(".trello-planner-day h3").first()).toContainText("Today");
  await planner.getByRole("button", { name: "Next day" }).click();
  await expect(planner.locator(".trello-planner-day h3").first()).toContainText("Tomorrow");
  await planner.getByRole("button", { name: "Today", exact: true }).click();
  await expect(planner.locator(".trello-planner-day h3").first()).toContainText("Today");

  await planner.getByRole("button", { name: "Planner month" }).click();
  const datePicker = page.getByRole("dialog", { name: "Select date" });
  await expect(datePicker).toBeVisible();
  const initialMonthHeading = await datePicker.locator(".trello-planner-date-picker__month strong").textContent();
  for (let index = 0; index < 14; index += 1) {
    await datePicker.getByRole("button", { name: "Next month" }).click();
  }
  const futureMonthHeading = await datePicker.locator(".trello-planner-date-picker__month strong").textContent();
  expect(futureMonthHeading).not.toBe(initialMonthHeading);
  expect(futureMonthHeading).toContain(String(new Date().getFullYear() + 1));

  const firstFutureDate = datePicker.locator(".trello-planner-date-picker__grid button:not(.is-outside)").first();
  await firstFutureDate.click();
  await expect(datePicker).toHaveCount(0);
  await expect(planner.getByRole("button", { name: "Planner month" })).toHaveAttribute("aria-expanded", "false");
  await expect(planner.locator(".trello-planner-day h3").first()).not.toContainText("Today");

  await planner.getByRole("button", { name: "Planner month" }).click();
  const pastPicker = page.getByRole("dialog", { name: "Select date" });
  for (let index = 0; index < 16; index += 1) {
    await pastPicker.getByRole("button", { name: "Previous month" }).click();
  }
  await expect(pastPicker.locator(".trello-planner-date-picker__month strong")).not.toContainText(
    String(new Date().getFullYear() + 1),
  );
  await pastPicker.getByRole("button", { name: "Close date picker" }).click();
  await planner.getByRole("button", { name: "Today", exact: true }).click();

  const plannerBeforeResize = await planner.boundingBox();
  const canvasBeforeResize = await canvas.boundingBox();
  const plannerResizeHandle = page.getByRole("separator", { name: "Resize Planner" });
  const plannerHandleBox = await plannerResizeHandle.boundingBox();
  expect(plannerBeforeResize).not.toBeNull();
  expect(canvasBeforeResize).not.toBeNull();
  expect(plannerHandleBox).not.toBeNull();
  await page.mouse.move(plannerHandleBox!.x + plannerHandleBox!.width / 2, plannerHandleBox!.y + 120);
  await page.mouse.down();
  await page.mouse.move(plannerHandleBox!.x + plannerHandleBox!.width / 2 + 70, plannerHandleBox!.y + 120);
  await page.mouse.up();
  const plannerAfterResize = await planner.boundingBox();
  const canvasAfterPlannerResize = await canvas.boundingBox();
  expect(plannerAfterResize).not.toBeNull();
  expect(canvasAfterPlannerResize).not.toBeNull();
  expect(plannerAfterResize!.width).toBeGreaterThan(plannerBeforeResize!.width + 45);
  expect(canvasAfterPlannerResize!.x).toBeGreaterThan(canvasBeforeResize!.x + 45);

  const inbox = page.locator(".trello-inbox");
  const inboxBeforeResize = await inbox.boundingBox();
  const inboxResizeHandle = page.getByRole("separator", { name: "Resize Inbox" });
  const inboxHandleBox = await inboxResizeHandle.boundingBox();
  expect(inboxBeforeResize).not.toBeNull();
  expect(inboxHandleBox).not.toBeNull();
  await page.mouse.move(inboxHandleBox!.x + inboxHandleBox!.width / 2, inboxHandleBox!.y + 120);
  await page.mouse.down();
  await page.mouse.move(inboxHandleBox!.x + inboxHandleBox!.width / 2 + 40, inboxHandleBox!.y + 120);
  await page.mouse.up();
  const inboxAfterResize = await inbox.boundingBox();
  expect(inboxAfterResize).not.toBeNull();
  expect(inboxAfterResize!.width).toBeGreaterThan(inboxBeforeResize!.width + 25);

  await planner.getByRole("button", { name: "Planner options" }).click();
  const menu = page.getByRole("menu", { name: "Planner menu" });
  await expect(menu.getByRole("menuitem")).toHaveCount(1);
  await expect(menu.getByRole("menuitem", { name: "Filter due cards shown" })).toBeVisible();
  await expect(menu.getByText("Add account")).toHaveCount(0);

  await menu.getByRole("menuitem", { name: "Filter due cards shown" }).click();
  const filter = page.getByRole("dialog", { name: "Filter due cards shown" });
  const assigned = filter.getByLabel("Cards assigned to me");
  const currentBoard = filter.getByLabel("Cards on this board");
  await expect(assigned).toBeChecked();
  await expect(currentBoard).toBeChecked();
  await expect(filter.getByText("More options")).toHaveCount(0);

  await filter.locator(".trello-planner-toggle-row").filter({ hasText: "Cards assigned to me" }).click();
  await expect(assigned).not.toBeChecked();
  await expect(planner.getByText("Planner assigned agenda item")).toBeVisible();
  await filter.locator(".trello-planner-toggle-row").filter({ hasText: "Cards on this board" }).click();
  await expect(currentBoard).not.toBeChecked();
  await expect(planner.getByText("Planner assigned agenda item")).toHaveCount(0);
  await filter.locator(".trello-planner-toggle-row").filter({ hasText: "Cards assigned to me" }).click();
  await expect(assigned).toBeChecked();
  await expect(planner.getByText("Planner assigned agenda item")).toBeVisible();

  await page.locator(".trello-dock button").filter({ hasText: "Planner" }).click();
  await expect(planner).toHaveCount(0);
  await expect(page.locator(".trello-workspace")).not.toHaveClass(/trello-workspace--planner/);

  const restored = await canvas.boundingBox();
  expect(restored).not.toBeNull();
  expect(restored!.x).toBeLessThan(canvasAfterPlannerResize!.x - 300);
  expect(restored!.width).toBeGreaterThan(canvasAfterPlannerResize!.width + 300);

  assertClean();
});


test("Version 2 Planner popovers remain fully visible at compact desktop widths", async ({ page }) => {
  await page.setViewportSize({ width: 1050, height: 760 });
  await login(page, env("E2E_MEMBER_USERNAME"));
  await openBoard(page);
  const assertClean = monitor(page);

  await expect(page.getByText("Consolidate your to-dos")).toHaveCount(0);
  await expect(page.locator(".trello-dock .trello-dock__icon")).toHaveCount(4);

  await page.locator(".trello-dock button").filter({ hasText: "Planner" }).click();
  const planner = page.getByRole("complementary", { name: "Planner" });
  await expect(planner).toBeVisible();

  const assertInsideViewport = async (locator: ReturnType<Page["locator"]>) => {
    const box = await locator.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(1050);
    expect(box!.y + box!.height).toBeLessThanOrEqual(760);
  };

  await planner.getByRole("button", { name: "Planner month" }).click();
  const datePicker = page.getByRole("dialog", { name: "Select date" });
  await expect(datePicker).toBeVisible();
  await assertInsideViewport(datePicker);
  await datePicker.getByRole("button", { name: "Close date picker" }).click();

  await planner.getByRole("button", { name: "Planner options" }).click();
  const menu = page.getByRole("menu", { name: "Planner menu" });
  await expect(menu).toBeVisible();
  await assertInsideViewport(menu);

  await menu.getByRole("menuitem", { name: "Filter due cards shown" }).click();
  const filter = page.getByRole("dialog", { name: "Filter due cards shown" });
  await expect(filter).toBeVisible();
  await assertInsideViewport(filter);

  assertClean();
});
