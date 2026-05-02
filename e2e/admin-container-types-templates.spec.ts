import { expect, test } from "@playwright/test";

test.describe.configure({ mode: "serial" });

const TYPE_PROBE = "e2e_probe";
const TYPE_JOB = "e2e_job";
const REQ_ALPINE = "e2e_alpine";

test("2E: admin container types + requirement templates (UI + build + API)", async ({
  page,
  request,
}) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];

  page.on("console", (msg) => {
    if (msg.type() === "error") {
      consoleErrors.push(msg.text());
    }
  });
  page.on("pageerror", (err) => {
    pageErrors.push(String(err));
  });
  page.on("dialog", (d) => {
    void d.accept();
  });

  const token = (process.env.FLEET_BEARER_TOKEN || "").trim();
  if (token) {
    await page.addInitScript((t: string) => {
      localStorage.setItem("forgeFleetAdminToken", t);
    }, token);
  }

  await page.goto("/admin/");
  await expect(page.locator("#fleet-version-line")).not.toContainText("Loading version", {
    timeout: 90_000,
  });

  await page.locator("#fleet-tab-containers-btn").click();
  await expect(page.locator("#fleet-container-types-wrap")).toBeVisible({ timeout: 90_000 });
  await expect(page.locator(`tr[data-fleet-type-id="empty"]`)).toBeVisible();

  await page.locator("#fleet-types-reload-btn").click();
  await expect(page.locator(`tr[data-fleet-type-id="empty"]`)).toBeVisible();

  // --- Add type e2e_probe (POST) ---
  const postType = page.waitForResponse(
    (r) =>
      r.url().includes("/v1/container-types") &&
      !r.url().includes(`/${TYPE_PROBE}`) &&
      r.request().method() === "POST",
  );
  await page.locator("#fleet-type-add-btn").click();
  await expect(page.locator("#fleet-type-edit-modal")).toBeVisible();
  await page.locator("#fleet-type-field-id").fill(TYPE_PROBE);
  await page.locator("#fleet-type-field-category").selectOption("job");
  await page.locator("#fleet-type-field-cclass").fill(TYPE_PROBE);
  await page.locator("#fleet-type-field-title").fill("E2E probe type");
  await page.locator("#fleet-type-field-notes").fill("playwright");
  await page.locator("#fleet-type-edit-save").click();
  const postTypeRes = await postType;
  expect([200, 201]).toContain(postTypeRes.status());
  expect((await postTypeRes.json()).ok).toBe(true);
  await expect(page.locator("#fleet-type-edit-modal")).toBeHidden({ timeout: 30_000 });
  await expect(page.locator(`tr[data-fleet-type-id="${TYPE_PROBE}"]`)).toBeVisible();

  // --- Edit e2e_probe (PUT) ---
  const putType = page.waitForResponse(
    (r) => r.url().endsWith(`/v1/container-types/${TYPE_PROBE}`) && r.request().method() === "PUT",
  );
  await page.locator(`tr[data-fleet-type-id="${TYPE_PROBE}"] button.fleet-type-edit`).click();
  await expect(page.locator("#fleet-type-edit-modal")).toBeVisible();
  await page.locator("#fleet-type-field-title").fill("E2E probe type (edited)");
  await page.locator("#fleet-type-edit-save").click();
  const putTypeRes = await putType;
  expect(putTypeRes.status()).toBe(200);
  expect((await putTypeRes.json()).ok).toBe(true);
  await expect(page.locator("#fleet-type-edit-modal")).toBeHidden({ timeout: 30_000 });

  // --- Delete e2e_probe (DELETE) ---
  const delProbe = page.waitForResponse(
    (r) => r.url().endsWith(`/v1/container-types/${TYPE_PROBE}`) && r.request().method() === "DELETE",
  );
  await page.locator(`tr[data-fleet-type-id="${TYPE_PROBE}"] button.fleet-type-del`).click();
  const delProbeRes = await delProbe;
  expect(delProbeRes.status()).toBe(200);
  expect((await delProbeRes.json()).ok).toBe(true);
  await expect(page.locator(`tr[data-fleet-type-id="${TYPE_PROBE}"]`)).toHaveCount(0);

  await expect(page.locator(`tr[data-fleet-type-id="empty"] button.fleet-type-del`)).toBeDisabled();

  // --- Requirement template: add row + Save templates (PUT) ---
  await page.locator("#fleet-req-template-add-btn").click();
  await expect(page.locator("#fleet-req-template-modal")).toBeVisible();
  await page.locator("#fleet-req-field-id").fill(REQ_ALPINE);
  await page.locator("#fleet-req-field-title").fill("E2E Alpine pin");
  await page.locator("#fleet-req-field-kind").selectOption("image");
  await page.locator("#fleet-req-field-ref").fill("alpine:3.20");
  await page.locator("#fleet-req-field-semver").fill("3.20.0");
  await page.locator("#fleet-req-edit-save").click();
  await expect(page.locator("#fleet-req-template-modal")).toBeHidden();
  await expect(page.locator("#fleet-requirement-templates-table")).toContainText(REQ_ALPINE);

  const putTemplates = page.waitForResponse(
    (r) => r.url().includes("/v1/container-templates") && r.request().method() === "PUT",
  );
  await page.locator("#fleet-req-templates-save-btn").click();
  const putTemplatesRes = await putTemplates;
  expect(putTemplatesRes.status()).toBe(200);
  const putTemplatesBody = await putTemplatesRes.json();
  expect(putTemplatesBody.ok).toBe(true);
  await expect(page.locator("#fleet-requirement-templates-editor-msg")).toContainText("Saved");

  // --- Build bundle (POST) — requires Docker + network unless image cached ---
  const buildDetails = page.locator("#fleet-requirement-templates-inner details");
  await buildDetails.locator("summary").click();
  await expect(page.locator("#fleet-build-req-ids")).toBeVisible();
  await expect(page.locator("#fleet-template-build-btn")).toBeVisible();
  await page.locator("#fleet-build-req-ids").fill(REQ_ALPINE);
  const postBuild = page.waitForResponse(
    (r) => r.url().includes("/v1/container-templates/build") && r.request().method() === "POST",
    { timeout: 300_000 },
  );
  await page.locator("#fleet-template-build-btn").scrollIntoViewIfNeeded();
  await page.locator("#fleet-template-build-btn").click();
  const postBuildRes = await postBuild;
  const postBuildBody = await postBuildRes.json().catch(() => ({}));
  if (!postBuildRes.ok() || postBuildBody.ok !== true) {
    test.skip(
      true,
      `Docker/template build unavailable (HTTP ${postBuildRes.status()}): ${JSON.stringify(postBuildBody).slice(0, 500)}`,
    );
  }
  await expect(page.locator("#fleet-template-build-result")).toContainText('"ok":true');

  // --- Type e2e_job with requirements ---
  const postJob = page.waitForResponse(
    (r) =>
      r.url().includes("/v1/container-types") &&
      !r.url().includes(`/${TYPE_JOB}`) &&
      r.request().method() === "POST",
  );
  await page.locator("#fleet-type-add-btn").click();
  await page.locator("#fleet-type-field-id").fill(TYPE_JOB);
  await page.locator("#fleet-type-field-category").selectOption("job");
  await page.locator("#fleet-type-field-cclass").fill(TYPE_JOB);
  await page.locator("#fleet-type-field-title").fill("E2E job with template");
  await page.locator("#fleet-type-field-req").fill(REQ_ALPINE);
  await page.locator("#fleet-type-edit-save").click();
  const postJobRes = await postJob;
  expect([200, 201]).toContain(postJobRes.status());
  expect((await postJobRes.json()).ok).toBe(true);
  await expect(page.locator(`tr[data-fleet-type-id="${TYPE_JOB}"]`)).toBeVisible();

  // --- Optional API checks (same base URL) ---
  const typesPayload = await request.get("/v1/container-types");
  expect(typesPayload.ok()).toBe(true);
  const typesJson = await typesPayload.json();
  expect(typesJson.ok).toBe(true);
  expect(typesJson.paths?.requirement_templates_file).toBeTruthy();

  const resolveUrl = `/v1/container-templates/resolve?requirements=${encodeURIComponent(REQ_ALPINE)}&build_if_missing=0`;
  const resolvePayload = await request.get(resolveUrl);
  expect(resolvePayload.ok()).toBe(true);
  const resolveJson = await resolvePayload.json();
  expect(resolveJson.ok).toBe(true);
  expect(String(resolveJson.image || "").trim().length).toBeGreaterThan(0);

  // --- Teardown: delete type + remove template row + save ---
  const delJob = page.waitForResponse(
    (r) => r.url().endsWith(`/v1/container-types/${TYPE_JOB}`) && r.request().method() === "DELETE",
  );
  await page.locator(`tr[data-fleet-type-id="${TYPE_JOB}"] button.fleet-type-del`).click();
  const delJobRes = await delJob;
  expect(delJobRes.status()).toBe(200);
  await expect(page.locator(`tr[data-fleet-type-id="${TYPE_JOB}"]`)).toHaveCount(0);

  const rowAlpine = page.locator("tr", { has: page.getByRole("cell", { name: REQ_ALPINE, exact: true }) });
  await rowAlpine.locator("button.fleet-req-del").click();
  const putTemplates2 = page.waitForResponse(
    (r) => r.url().includes("/v1/container-templates") && r.request().method() === "PUT",
  );
  await page.locator("#fleet-req-templates-save-btn").click();
  const putTemplates2Res = await putTemplates2;
  expect(putTemplates2Res.status()).toBe(200);
  expect((await putTemplates2Res.json()).ok).toBe(true);
  await expect(page.locator("#fleet-requirement-templates-table")).not.toContainText(REQ_ALPINE);

  expect(
    consoleErrors,
    `Unexpected console errors: ${consoleErrors.join("\n---\n")}`,
  ).toEqual([]);
  expect(pageErrors, `Unexpected page errors: ${pageErrors.join("\n---\n")}`).toEqual([]);
});
