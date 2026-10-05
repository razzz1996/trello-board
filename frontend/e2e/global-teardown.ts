import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

export default async function globalTeardown() {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const projectRoot = path.resolve(here, "../..");
  const required = [
    "E2E_ADMIN_USERNAME",
    "E2E_MEMBER_USERNAME",
    "E2E_MEMBER2_USERNAME",
    "E2E_PASSWORD",
    "E2E_BOARD_NAME",
  ];
  if (required.some((name) => !process.env[name])) return;

  const python = path.join(projectRoot, ".venv", "Scripts", "python.exe");
  try {
    execFileSync(
      python,
      [path.join(here, "fixture_productivity.py"), "cleanup"],
      { cwd: projectRoot, env: process.env, stdio: "pipe" },
    );
  } catch {
    // Preserve the E2E result; cleanup is retried manually during operator validation.
  }

  const monthlyRoot =
    process.env.E2E_MONTHLY_ROOT ?? String.raw`C:\Users\PC 19\Desktop\MONTHLY EVALUATION`;
  const monthlyPython = path.join(monthlyRoot, ".venv", "Scripts", "python.exe");
  try {
    execFileSync(
      monthlyPython,
      [path.join(here, "fixture_monthly.py"), "cleanup"],
      {
        cwd: monthlyRoot,
        env: { ...process.env, HR_EVALUATIONS_ENABLED: "1" },
        stdio: "pipe",
      },
    );
  } catch {
    // Preserve the E2E result; cleanup is retried manually during operator validation.
  }
}
