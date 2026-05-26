    }

    function statusPill(st) {
      var c = "fleet-pill st-" + String(st || "").toLowerCase();
      return '<span class="' + c + '">' + esc(st || "?") + "</span>";
    }

    /** Human-readable job outcome for tables and detail header. */
    function jobOutcomeHuman(j) {
      var st = String(j.status || "").toLowerCase();
      var ex = j.exit_code;
      if (st === "queued") return { cls: "text-body-secondary", text: "Queued" };
      if (st === "running") return { cls: "text-warning", text: "Running…" };
      if (st === "cancelled") return { cls: "text-body-secondary", text: "Cancelled" };
      if (st === "failed") {
        if (ex != null && ex !== "") return { cls: "text-danger", text: "Failed · exit " + ex };
        return { cls: "text-danger", text: "Failed" };
      }
      if (st === "completed") {
        if (ex === 0 || ex === "0") return { cls: "text-success", text: "Succeeded" };
        if (ex != null && ex !== "") return { cls: "text-danger", text: "Finished · exit " + ex };
        return { cls: "text-success", text: "Finished" };
      }
      return { cls: "text-body-secondary", text: String(j.status || "—") };
    }

    function fleetJobArgvShell(argv) {
      if (!argv || !argv.length) return "";
      return argv
        .map(function (x) {
          var s = String(x);
          if (/[\s'"\\]/.test(s)) return "'" + s.replace(/'/g, "'\\''") + "'";
          return s;
        })
        .join(" ");
    }

    function renderFleetJobDetailPayload(j) {
      if (!j || !j.ok) {
        return "<p class=\"text-danger mb-0\">Could not load job.</p>";
      }
      var oid = jobOutcomeHuman(j);
      var parts = [];
      parts.push("<dl class=\"row mb-3 small\">");
      parts.push("<dt class=\"col-sm-3 text-body-secondary\">Status</dt><dd class=\"col-sm-9\">" + statusPill(j.status) + "</dd>");
      parts.push(
        "<dt class=\"col-sm-3 text-body-secondary\">Outcome</dt><dd class=\"col-sm-9\"><span class=\"" +
          oid.cls +
          "\">" +
          esc(oid.text) +
          "</span></dd>"
      );
      parts.push(
        "<dt class=\"col-sm-3 text-body-secondary\">Job ID</dt><dd class=\"col-sm-9\"><code class=\"fleet-mono user-select-all\">" +
          esc(j.id || "") +
          "</code></dd>"
      );
      if (j.session_id)
        parts.push(
          "<dt class=\"col-sm-3 text-body-secondary\">Session</dt><dd class=\"col-sm-9\"><code class=\"fleet-mono user-select-all\">" +
            esc(j.session_id) +
            "</code></dd>"
        );
      if (j.kind) parts.push("<dt class=\"col-sm-3 text-body-secondary\">Kind</dt><dd class=\"col-sm-9\">" + esc(j.kind) + "</dd>");
      if (j.container_id)
        parts.push(
          "<dt class=\"col-sm-3 text-body-secondary\">Container</dt><dd class=\"col-sm-9\"><code class=\"fleet-mono\">" +
            esc(j.container_id) +
            "</code></dd>"
        );
      if (j.created != null)
        parts.push("<dt class=\"col-sm-3 text-body-secondary\">Created</dt><dd class=\"col-sm-9\">" + esc(fmtTime(j.created)) + "</dd>");
      if (j.updated != null)
        parts.push("<dt class=\"col-sm-3 text-body-secondary\">Updated</dt><dd class=\"col-sm-9\">" + esc(fmtTime(j.updated)) + "</dd>");
      parts.push("</dl>");
      var meta = j.meta && typeof j.meta === "object" ? j.meta : {};
      if (Object.keys(meta).length) {
        parts.push("<h6 class=\"text-body-secondary text-uppercase small mb-2\">Meta (JSON)</h6>");
        parts.push(
          "<pre class=\"fleet-mono small bg-body-secondary border rounded p-2 mb-3\" style=\"max-height:12rem;overflow:auto\">" +
            esc(JSON.stringify(meta, null, 2)) +
            "</pre>"
        );
      }
      if (j.argv && j.argv.length) {
        parts.push("<h6 class=\"text-body-secondary text-uppercase small mb-2\">Docker command</h6>");
        parts.push(
          "<pre class=\"fleet-mono small bg-body-secondary border rounded p-2 mb-3\" style=\"max-height:14rem;overflow:auto;white-space:pre-wrap\">" +
            esc(fleetJobArgvShell(j.argv)) +
            "</pre>"
        );
      }
      var out = (j.stdout || "").trim();
      var err = (j.stderr || "").trim();
      if (out) {
        parts.push("<h6 class=\"text-body-secondary text-uppercase small mb-2\">Stdout</h6>");
        parts.push(
          "<pre class=\"fleet-mono small bg-body-secondary border rounded p-2 mb-3\" style=\"max-height:14rem;overflow:auto;white-space:pre-wrap\">" +
            esc(out.length > 120000 ? out.slice(0, 120000) + "\n… truncated" : out) +
            "</pre>"
        );
      }
      if (err) {
        parts.push("<h6 class=\"text-body-secondary text-uppercase small mb-2\">Stderr</h6>");
        parts.push(
          "<pre class=\"fleet-mono small bg-danger-subtle border border-danger-subtle rounded p-2 mb-0\" style=\"max-height:14rem;overflow:auto;white-space:pre-wrap\">" +
            esc(err.length > 120000 ? err.slice(0, 120000) + "\n… truncated" : err) +
            "</pre>"
        );
      }
      return parts.join("");
    }

    async function openFleetJobDetail(jobId) {
      var el = document.getElementById("fleet-job-detail-modal");
      var body = document.getElementById("fleet-job-detail-body");
      if (!el || !body) return;
      body.innerHTML = "<p class=\"text-body-secondary mb-0\">Loading…</p>";
      if (typeof bootstrap !== "undefined" && bootstrap.Modal) {
        bootstrap.Modal.getOrCreateInstance(el).show();
      }
      try {
        var res = await fetch("/v1/jobs/" + encodeURIComponent(jobId), { headers: authHeaders(), cache: "no-store" });
        var j = {};
        try {
          j = await res.json();
        } catch (_e) {
          j = {};
        }
        if (!res.ok) {
          body.innerHTML =
            "<p class=\"text-danger mb-0\">HTTP " +
            res.status +
            " — " +
            esc(String(j.error || res.statusText || "error")) +
            "</p>";
          return;
        }
        body.innerHTML = renderFleetJobDetailPayload(j);
      } catch (e) {
        body.innerHTML = "<p class=\"text-danger mb-0\">" + esc(String(e)) + "</p>";
      }
    }

    function authHeaders() {
      var t = (localStorage.getItem(LS) || "").trim();
      var h = { Accept: "application/json" };
      if (t) h.Authorization = "Bearer " + t;
      return h;
    }

    function setErr(msg) {
      if (!msg) {
        errEl.classList.add("d-none");
        errEl.textContent = "";
        return;
      }
      errEl.textContent = msg;
      errEl.classList.remove("d-none");
    }

    function renderManagedServices(integ) {
      var wrap = document.getElementById("fleet-managed-services-wrap");
      var pathsEl = document.getElementById("fleet-config-paths");
      var rowsEl = document.getElementById("fleet-managed-services-rows");
      var msgEl = document.getElementById("fleet-svc-action-msg");
      if (!wrap || !pathsEl || !rowsEl) return;
      var cl = integ.container_layout;
      if (!cl) {
        wrap.classList.add("d-none");
        return;
      }
      wrap.classList.remove("d-none");
      pathsEl.textContent =
        "types_file=" +
        cl.types_file +
        " · services_dir=" +
        cl.services_dir +
        (cl.requirement_templates_file ? " · req_templates=" + cl.requirement_templates_file : "") +
        (cl.build_cache_file ? " · build_cache=" + cl.build_cache_file : "");
      if (msgEl) msgEl.textContent = "";
      var svcs = integ.forge_llm_services || [];
      if (!svcs.length) {
        rowsEl.innerHTML =
          "<p class=\"text-body-secondary mb-0\">No <code class=\"fleet-mono\">forge_llm</code> services yet. Use <strong>Register stack</strong> below, or set <code class=\"fleet-mono\">FLEET_FORGE_LLM_ROOT</code> and restart Fleet once to auto-create <code class=\"fleet-mono\">default.json</code>.</p>";
        return;
      }
      var head =
        "<div class=\"table-responsive\"><table class=\"table table-sm table-bordered mb-0 fleet-mono\"><thead><tr>" +
        "<th>id</th><th>label</th><th>compose</th><th>status</th><th></th></tr></thead><tbody>";
      var body = svcs
        .map(function (s) {
          var st = (s.services_running != null ? s.services_running : "—") + " / " + (s.services_total != null ? s.services_total : "—") + " running";
          if (s.ps_ok === false) st += " · ps failed";
          var root = String(s.compose_root || "").slice(0, 48) + (String(s.compose_root || "").length > 48 ? "…" : "");
          var cf = (s.compose_files || []).join(", ") || "compose.yaml";
          var sid = String(s.id || "");
          return (
            "<tr><td>" +
            esc(sid) +
            "</td><td>" +
            esc(s.label || "") +
            "</td><td title=\"" +
            esc(String(s.compose_root || "")) +
            "\">" +
            esc(root) +
            "<div class=\"small text-body-secondary\">" +
            esc(cf) +
            "</div></td><td>" +
            esc(st) +
            "</td><td class=\"text-nowrap\"><button type=\"button\" class=\"btn btn-sm btn-outline-success me-1 fleet-svc-start\" data-svc-id=\"" +
            esc(sid) +
            "\">Start</button><button type=\"button\" class=\"btn btn-sm btn-outline-warning fleet-svc-stop\" data-svc-id=\"" +
            esc(sid) +
            "\">Stop</button></td></tr>"
          );
        })
        .join("");
      rowsEl.innerHTML = head + body + "</tbody></table></div>";
    }

    var __fleetTypesLoaded = false;
    var __fleetTypesDoc = null;
    var __fleetReqTemplatesDoc = null;
    var __fleetTypeEditMode = "add";
    var __fleetReqEditIdx = -1;

    function renderFleetReqTemplatesTable(doc) {
      if (!doc || !doc.ok) return;
      __fleetReqTemplatesDoc = doc;
      var tbl = document.getElementById("fleet-requirement-templates-table");
      if (!tbl) return;
      var templates = Array.isArray(doc.templates) ? doc.templates : [];
      var head =
        '<div class="table-responsive"><table class="table table-sm table-bordered mb-0 fleet-mono"><thead><tr>' +
        "<th>id</th><th>kind</th><th>ref</th><th>title</th><th class=\"text-end\">actions</th></tr></thead><tbody>";
      var body = templates
        .map(function (row, idx) {
          var rid = esc(String((row && row.id) || ""));
          return (
            "<tr><td>" +
            rid +
            "</td><td>" +
            esc(String((row && row.kind) || "")) +
            "</td><td class=\"small\" title=\"" +
            esc(String((row && row.ref) || "")) +
            "\">" +
            esc(String((row && row.ref) || "").slice(0, 72)) +
            (String((row && row.ref) || "").length > 72 ? "…" : "") +
            "</td><td class=\"small\">" +
            esc(String((row && row.title) || "")) +
            "</td><td class=\"text-end text-nowrap\"><button type=\"button\" class=\"btn btn-sm btn-outline-primary fleet-req-edit\" data-req-idx=\"" +
            idx +
            "\">Edit</button> <button type=\"button\" class=\"btn btn-sm btn-outline-danger fleet-req-del\" data-req-idx=\"" +
            idx +
            "\">Remove</button></td></tr>"
          );
        })
        .join("");
      tbl.innerHTML =
        head +
        body +
        (templates.length ? "" : '<tr><td colspan="5" class="text-body-secondary">No templates yet.</td></tr>') +
        "</tbody></table></div>";
    }

    async function loadRequirementTemplatesOnce(force) {
      try {
        var res = await fetch("/v1/container-templates", { headers: authHeaders(), cache: "no-store" });
        if (!res.ok) return;
        var doc = await res.json();
        renderFleetReqTemplatesTable(doc);
      } catch (_e) {
        /* ignore */
      }
    }

    function openFleetTypeModal(mode, typeId) {
      var err = document.getElementById("fleet-type-edit-err");
      if (err) {
        err.textContent = "";
        err.classList.add("d-none");
      }
      __fleetTypeEditMode = mode;
      var idEl = document.getElementById("fleet-type-field-id");
      var catEl = document.getElementById("fleet-type-field-category");
      var cclEl = document.getElementById("fleet-type-field-cclass");
      var titleEl = document.getElementById("fleet-type-field-title");
      var notesEl = document.getElementById("fleet-type-field-notes");
      var reqEl = document.getElementById("fleet-type-field-req");
      var capA = document.getElementById("fleet-type-cap-admin");
      var capApi = document.getElementById("fleet-type-cap-api");
      var capDr = document.getElementById("fleet-type-cap-docker");
      if (catEl) {
        catEl.innerHTML = "";
        (Array.isArray(__fleetTypesDoc && __fleetTypesDoc.categories) ? __fleetTypesDoc.categories : []).forEach(function (c) {
          if (!c || !c.id) return;
          var o = document.createElement("option");
          o.value = String(c.id);
          o.textContent = String(c.title || c.id);
          catEl.appendChild(o);
        });
      }
      if (mode === "add") {
        if (idEl) {
          idEl.value = "";
          idEl.readOnly = false;
        }
        if (cclEl) cclEl.value = "";
        if (titleEl) titleEl.value = "";
        if (notesEl) notesEl.value = "";
        if (reqEl) reqEl.value = "";
        if (catEl) catEl.value = "job";
        if (capA) capA.checked = false;
        if (capApi) capApi.checked = false;
        if (capDr) capDr.checked = false;
        var h = document.getElementById("fleet-type-edit-hint");
        if (h) h.textContent = "Add a new row to types.json (POST /v1/container-types).";
        var title = document.getElementById("fleet-type-edit-modal-label");
        if (title) title.textContent = "Add container type";
      } else {
        var mat = Array.isArray(__fleetTypesDoc && __fleetTypesDoc.types_materialized)
          ? __fleetTypesDoc.types_materialized
          : [];
        var row = null;
        for (var i = 0; i < mat.length; i++) {
          if (String((mat[i] && mat[i].id) || "") === String(typeId || "")) {
            row = mat[i];
            break;
          }
        }
        if (!row) return;
        if (idEl) {
          idEl.value = String(row.id || "");
          idEl.readOnly = true;
        }
        if (catEl) catEl.value = String(row.category_id || "job");
        if (cclEl) cclEl.value = String(row.container_class || "");
        if (titleEl) titleEl.value = String(row.title || "");
        if (notesEl) notesEl.value = String(row.notes || "");
        if (reqEl) reqEl.value = Array.isArray(row.requirements) ? row.requirements.join(", ") : "";
        var ec = row.effective_capabilities || {};
        if (capA) capA.checked = "admin_spawnable" in row ? !!row.admin_spawnable : !!ec.admin_spawnable;
        if (capApi) capApi.checked = "api_manage_services" in row ? !!row.api_manage_services : !!ec.api_manage_services;
        if (capDr) capDr.checked = "allow_docker_argv_jobs" in row ? !!row.allow_docker_argv_jobs : !!ec.allow_docker_argv_jobs;
        var h2 = document.getElementById("fleet-type-edit-hint");
        if (h2) h2.textContent = "Update this row (PUT /v1/container-types/{id}).";
        var title2 = document.getElementById("fleet-type-edit-modal-label");
        if (title2) title2.textContent = "Edit container type";
      }
      var modalEl = document.getElementById("fleet-type-edit-modal");
      if (modalEl && typeof bootstrap !== "undefined" && bootstrap.Modal) {
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    }

    function openFleetReqTemplateModal(idx) {
      var err = document.getElementById("fleet-req-edit-err");
      if (err) {
        err.textContent = "";
        err.classList.add("d-none");
      }
      __fleetReqEditIdx = typeof idx === "number" ? idx : -1;
      var templates = __fleetReqTemplatesDoc && Array.isArray(__fleetReqTemplatesDoc.templates)
        ? __fleetReqTemplatesDoc.templates
        : [];
      var row = __fleetReqEditIdx >= 0 ? templates[__fleetReqEditIdx] : null;
      var idEl = document.getElementById("fleet-req-field-id");
      var titleEl = document.getElementById("fleet-req-field-title");
      var kindEl = document.getElementById("fleet-req-field-kind");
      var refEl = document.getElementById("fleet-req-field-ref");
      var notesEl = document.getElementById("fleet-req-field-notes");
      if (row && typeof row === "object") {
        if (idEl) {
          idEl.value = String(row.id || "");
          idEl.readOnly = true;
        }
        if (titleEl) titleEl.value = String(row.title || "");
        if (kindEl) kindEl.value = String(row.kind || "dockerfile");
        if (refEl) refEl.value = String(row.ref || "");
        if (notesEl) notesEl.value = String(row.notes || "");
      } else {
        if (idEl) {
          idEl.value = "";
          idEl.readOnly = false;
        }
        if (titleEl) titleEl.value = "";
        if (kindEl) kindEl.value = "dockerfile";
        if (refEl) refEl.value = "";
        if (notesEl) notesEl.value = "";
      }
      var modalEl = document.getElementById("fleet-req-template-modal");
      if (modalEl && typeof bootstrap !== "undefined" && bootstrap.Modal) {
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    }

    async function loadContainerTypesOnce(force) {
      if (__fleetTypesLoaded && !force) return;
      try {
        var res = await fetch("/v1/container-types", { headers: authHeaders(), cache: "no-store" });
        if (!res.ok) return;
        var doc = await res.json();
        if (!doc.ok || !Array.isArray(doc.types)) return;
        __fleetTypesDoc = doc;
        __fleetTypesLoaded = true;
        var wrap = document.getElementById("fleet-container-types-wrap");
        var tbl = document.getElementById("fleet-container-types-table");
        if (!wrap || !tbl) return;
        wrap.classList.remove("d-none");
        var mat = Array.isArray(doc.types_materialized) ? doc.types_materialized : [];
        function effCaps(t) {
          var e = t && t.effective_capabilities;
          return e && typeof e === "object" ? e : {};
        }
        var head =
          '<div class="table-responsive"><table class="table table-sm table-bordered mb-0 fleet-mono"><thead><tr>' +
          "<th>id</th><th>category</th><th>container_class</th><th>requirements</th><th>telemetry</th><th class=\"text-end\">actions</th></tr></thead><tbody>";
        var body = mat
          .map(function (t) {
            var tid = String((t && t.id) || "");
            var cid = String((t && t.category_id) || "");
            var cclass = String((t && t.container_class) || "");
            var reqs = Array.isArray(t.requirements) ? t.requirements.join(", ") : "";
            var ec = effCaps(t);
            var caps =
              "adm " +
              (ec.admin_spawnable ? "Y" : "n") +
              " · svc " +
              (ec.api_manage_services ? "Y" : "n") +
              " · dock " +
              (ec.allow_docker_argv_jobs ? "Y" : "n");
            return (
              "<tr class=\"fleet-type-card\" data-fleet-type-id=\"" +
              esc(tid) +
              "\" data-category-id=\"" +
              esc(cid) +
              "\" data-container-class=\"" +
              esc(cclass) +
              "\"><td>" +
              esc(tid) +
              "</td><td>" +
              esc(cid) +
              "</td><td>" +
              esc(cclass) +
              "</td><td class=\"small\">" +
              esc(reqs) +
              "</td><td class=\"small\"><span data-fleet-type-tel>—</span><div class=\"text-body-secondary\">" +
              esc(caps) +
              "</div></td><td class=\"text-nowrap text-end\"><button type=\"button\" class=\"btn btn-sm btn-outline-primary me-1 fleet-type-edit\" data-type-id=\"" +
              esc(tid) +
              "\">Edit</button><button type=\"button\" class=\"btn btn-sm btn-outline-danger fleet-type-del\" data-type-id=\"" +
              esc(tid) +
              "\"" +
              (tid === "empty" ? " disabled" : "") +
              ">Delete</button></td></tr>"
            );
          })
          .join("");
        tbl.innerHTML =
          head +
          body +
          (mat.length ? "" : '<tr><td colspan="6" class="text-body-secondary">No types.</td></tr>') +
          "</tbody></table></div>";
        refreshContainerTypesTelemetry(__fleetLastOrchestration);
        await loadRequirementTemplatesOnce(force);
      } catch (_e) {
        /* ignore */
      }
    }

    function fleetUpdateUiRefresh() {
      /* Git update affordance lives in #fleet-git-remote-row (checkRemoteAgainstGitHub). */
    }

    function applySelfUpdateMeta(su) {
      __fleetSelfUpdateMeta = su || {};
    }

    function showSystemUpdateModal(commandText) {
      var pre = document.getElementById("fleet-system-update-command");
      var el = document.getElementById("fleet-system-update-modal");
      if (pre) {
        pre.textContent =
          commandText && String(commandText).trim()
            ? String(commandText)
            : "(No command — check FLEET_GIT_ROOT and install-update.sh in the clone.)";
      }
      if (el && typeof bootstrap !== "undefined" && bootstrap.Modal) {
        bootstrap.Modal.getOrCreateInstance(el).show();
      }
    }

    function formatSelfUpdateSteps(steps) {
      if (!Array.isArray(steps) || !steps.length) return "";
      return steps
        .map(function (s) {
          var out = (s.stdout || "").trim();
          var err = (s.stderr || "").trim();
          var body = (out + (out && err ? "\n" : "") + err).trim();
          return (
            "— " +
            esc(s.step || "") +
            " (exit " +
            esc(String(s.returncode != null ? s.returncode : "?")) +
            ")\n" +
            esc(body).slice(0, 12000)
          );
        })
        .join("\n\n");
    }

    async function waitFleetBack(maxMs) {
      var deadline = Date.now() + maxMs;
      while (Date.now() < deadline) {
        try {
          var res = await fetch("/v1/version", { headers: authHeaders(), cache: "no-store" });
          if (res.ok) return true;
        } catch (_e) {
          /* server restarting */
        }
        await new Promise(function (r) {
          setTimeout(r, 400);
        });
      }
      return false;
    }

    async function doGitSelfUpdate() {
      var st = document.getElementById("fleet-self-update-status");
      var logEl = document.getElementById("fleet-self-update-log");
      if (!__fleetSelfUpdateConfigured) {
        setErr(
          "Git self-update is not configured. Set FLEET_GIT_ROOT to your forge-fleet checkout (with .git), or run this Fleet process from that clone."
        );
        return;
      }
      var su = __fleetSelfUpdateMeta || {};
      if (String(su.install_profile || "user").toLowerCase() === "system") {
        return;
      }
      setErr("");
      if (st) st.textContent = "Running git pull…";
      if (logEl) {
        logEl.textContent = "";
        logEl.classList.add("d-none");
      }
      try {
        var res = await fetch("/v1/admin/git-self-update", {
          method: "POST",
          headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
          body: "{}",
        });
        var j = {};
        try {
          j = await res.json();
        } catch (_e) {
          j = {};
        }
        if (logEl && j.steps) {
          logEl.textContent = formatSelfUpdateSteps(j.steps);
          logEl.classList.remove("d-none");
        }
        if (!res.ok || !j.ok) {
          if (st) st.textContent = "Failed (" + res.status + ").";
          setErr(String(j.detail || j.error || "git-self-update failed"));
          return;
        }
        if (st) st.textContent = j.note || "OK.";
        if (j.scheduled_restart) {
          if (st) st.textContent = (j.note || "") + " Waiting for Fleet to come back…";
          await new Promise(function (r) {
            setTimeout(r, j.reload_after_ms || 2200);
          });
          var ok = await waitFleetBack(45000);
          if (st) st.textContent = ok ? "Reloading…" : "Fleet did not respond in time — reload manually.";
          if (ok) window.location.reload();
        }
      } catch (e) {
        setErr(String(e));
        if (st) st.textContent = "";
      }
    }

    function gitShaPrefix7(s) {
      return String(s || "")
        .toLowerCase()
        .replace(/[^a-f0-9]/g, "")
        .slice(0, 7);
    }

    async function checkRemoteAgainstGitHub() {
      var row = document.getElementById("fleet-git-remote-row");
      if (!row) return;
      var localRaw = (__fleetLocalGitSha || "").trim();
      if (!localRaw) {
        row.innerHTML =
          '<span class="opacity-75">No git SHA from server — cannot compare to GitHub.</span>';
        __fleetGitUpdateAvailable = false;
        fleetUpdateUiRefresh();
        return;
      }
      try {
        var res = await fetch("https://api.github.com/repos/" + FLEET_GITHUB_REPO + "/commits/master", {
          headers: { Accept: "application/vnd.github+json" },
        });
        if (!res.ok) {
          row.innerHTML =
            '<span class="opacity-75">GitHub check failed (HTTP ' +
            esc(String(res.status)) +
            ").</span>";
          __fleetGitUpdateAvailable = false;
          fleetUpdateUiRefresh();
          return;
        }
        var j = await res.json();
        var remoteFull = (j.sha || "").trim();
        if (!remoteFull) {
          row.textContent = "";
          __fleetGitUpdateAvailable = false;
          fleetUpdateUiRefresh();
          return;
        }
        var a = gitShaPrefix7(localRaw);
        var b = gitShaPrefix7(remoteFull);
        if (a && b && a === b) {
          row.innerHTML = '<span class="opacity-75">GitHub master matches this host.</span>';
          __fleetGitUpdateAvailable = false;
          fleetUpdateUiRefresh();
          return;
        }
        __fleetGitUpdateAvailable = !!(a && b && a !== b);
        var commitsHref = "https://github.com/" + FLEET_GITHUB_REPO + "/commits/master";
        var profileGh = String((__fleetSelfUpdateMeta || {}).install_profile || "user").toLowerCase();
        if (__fleetSelfUpdateConfigured && profileGh !== "system") {
          row.innerHTML =
            '<span class="text-warning fw-semibold me-1">Update available</span>' +
            '<button type="button" class="btn btn-sm btn-warning" id="fleet-header-git-update-btn">Update Fleet</button>' +
            '<a class="btn btn-sm btn-outline-secondary ms-1" href="' +
            commitsHref +
            '" target="_blank" rel="noopener">GitHub</a>';
        } else if (__fleetSelfUpdateConfigured && profileGh === "system") {
          row.innerHTML =
            '<span class="text-warning fw-semibold me-1">Update available</span>' +
            '<a class="btn btn-sm btn-outline-warning" href="' +
            commitsHref +
            '" target="_blank" rel="noopener">View commits</a>' +
            '<span class="text-body-secondary ms-1 small">System install — update on the host.</span>';
        } else {
          row.innerHTML =
            '<span class="text-warning fw-semibold me-1">Newer commits on GitHub</span>' +
            '<a class="btn btn-sm btn-outline-warning" href="' +
            commitsHref +
            '" target="_blank" rel="noopener">View commits</a>' +
            '<span class="text-body-secondary ms-1" style="font-size:0.72rem">Enable git self-update on Fleet to pull here.</span>';
        }
        fleetUpdateUiRefresh();
      } catch (_e) {
        row.innerHTML = '<span class="opacity-75">Could not reach GitHub.</span>';
        __fleetGitUpdateAvailable = false;
        fleetUpdateUiRefresh();
      }
    }

    function renderFleetJobsPager(data, rows) {
      var pager = document.getElementById("fleet-jobs-pager");
      if (!pager) return;
      var jtot = data.jobs_recent_total != null ? Number(data.jobs_recent_total) : 0;
      var jlim = data.jobs_recent_limit != null ? Number(data.jobs_recent_limit) : fleetJobsPageSize;
      var joff = data.jobs_recent_offset != null ? Number(data.jobs_recent_offset) : fleetJobsOffset;
      if (!isNaN(jlim) && jlim > 0) fleetJobsPageSize = jlim;
      if (!isNaN(joff) && joff >= 0) fleetJobsOffset = joff;
      if (jtot <= 0) {
        pager.innerHTML = "";
