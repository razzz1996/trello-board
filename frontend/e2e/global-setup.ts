import { execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";
import path from "node:path";

export default async function globalSetup() {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const projectRoot = path.resolve(here, "../..");
  const suffix = Date.now().toString(36) + randomBytes(3).toString("hex");

  process.env.E2E_ADMIN_USERNAME = `e2e-admin-${suffix}`;
  process.env.E2E_MEMBER_USERNAME = `e2e-member-${suffix}`;
  process.env.E2E_MEMBER2_USERNAME = `e2e-member2-${suffix}`;
  process.env.E2E_PASSWORD = `E2E!${randomBytes(18).toString("base64url")}Aa1`;
  process.env.E2E_BOARD_NAME = `E2E Browser Board ${suffix}`;

  const python = path.join(projectRoot, ".venv", "Scripts", "python.exe");
  execFileSync(
    python,
    [path.join(here, "fixture_productivity.py"), "setup"],
    { cwd: projectRoot, env: process.env, stdio: "pipe" },
  );

  const monthlyRoot =
    process.env.E2E_MONTHLY_ROOT ?? String.raw`C:\Users\PC 19\Desktop\MONTHLY EVALUATION`;
  const monthlyPython = path.join(monthlyRoot, ".venv", "Scripts", "python.exe");
  execFileSync(
    monthlyPython,
    [path.join(here, "fixture_monthly.py"), "setup"],
    {
      cwd: monthlyRoot,
      env: { ...process.env, HR_EVALUATIONS_ENABLED: "1" },
      stdio: "pipe",
    },
  );
}
