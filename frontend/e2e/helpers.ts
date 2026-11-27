import type { APIRequestContext, Page } from "@playwright/test";

export const API = process.env.E2E_API_URL ?? "http://127.0.0.1:8010";
export const PASSWORD = "a-strong-test-password";

/** Accounts a spec created, deleted again after it so test runs leave no trace. */
const created: { email: string; password: string }[] = [];

export function track(email: string, password = PASSWORD) {
  created.push({ email, password });
}

export async function cleanupAccounts(request: APIRequestContext) {
  while (created.length) {
    const { email, password } = created.pop()!;
    const login = await request.post(`${API}/api/v1/auth/login`, { data: { email, password } });
    if (!login.ok()) continue;
    const { access_token } = await login.json();
    await request.post(`${API}/api/v1/me/delete`, {
      headers: { Authorization: `Bearer ${access_token}` }, data: { password },
    });
  }
}

/** Register through the API and sign the page in. */
export async function signUpViaApi(page: Page, prefix = "e2e") {
  const email = `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e4)}@example.com`;
  const res = await page.request.post(`${API}/api/v1/auth/register`, {
    data: { email, password: PASSWORD, full_name: "Trader" },
  });
  if (!res.ok()) throw new Error(`register failed: ${res.status()}`);
  track(email);
  const { access_token } = await res.json();
  await page.addInitScript((t) => localStorage.setItem("wealthos.token", t), access_token);
  return { email, token: access_token as string };
}
