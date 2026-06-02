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
        return;
      }
      var n = rows.length;
      var start = n === 0 ? 0 : joff + 1;
      var end = joff + n;
      var prevDis = joff <= 0 ? " disabled" : "";
      var nextDis = end >= jtot ? " disabled" : "";
      pager.innerHTML =
        '<nav class="d-flex flex-wrap align-items-center justify-content-between gap-2 small" aria-label="Job pages">' +
        '<span class="text-body-secondary">Showing <strong>' +
        start +
        "</strong>–<strong>" +
        end +
        '</strong> of <strong>' +
        jtot +
        '</strong> · ' +
        jlim +
        ' per page</span>' +
        '<div class="btn-group btn-group-sm" role="group">' +
        '<button type="button" class="btn btn-outline-secondary fleet-jobs-page-prev"' +
        prevDis +
        '>Previous</button>' +
        '<button type="button" class="btn btn-outline-secondary fleet-jobs-page-next"' +
        nextDis +
        '>Next</button>' +
        "</div></nav>";
    }
    async function fetchAdminSnapshot() {
      setErr("");
      var res;
      try {
        var snapPath =
          "/v1/admin/snapshot?jobs_limit=" +
          encodeURIComponent(String(fleetJobsPageSize)) +
          "&jobs_offset=" +
          encodeURIComponent(String(fleetJobsOffset));
        res = await fetch(snapPath, { headers: authHeaders(), cache: "no-store" });
      } catch (e) {
        setErr("Network: " + e);
        return null;
      }
      if (res.status === 401) {
        setErr("Unauthorized — send Authorization: Bearer … matching FLEET_BEARER_TOKEN (or use loopback-only bind).");
        return null;
      }
      if (!res.ok) {
        setErr("HTTP " + res.status);
        return null;
      }
      var data = await res.json();
      if (!data.ok) {
        setErr(JSON.stringify(data));
        return null;
      }
      return data;
    }
    async function applySnapshotData(data) {
      var meta = data.meta || {};
      var ver = meta.version || {};
      var vl = document.getElementById("fleet-version-line");
      if (vl) {
        var sha = ver.git_sha ? " · git " + String(ver.git_sha).slice(0, 7) : "";
        vl.textContent =
          "v" +
          String(ver.package_semver || "—") +
          " · DB schema " +
          String(ver.db_schema_version != null ? ver.db_schema_version : "—") +
          " · template lib " +
          String(ver.template_lib_version != null ? ver.template_lib_version : "—") +
          sha;
      }
      __fleetLocalGitSha = ver.git_sha ? String(ver.git_sha).trim() : "";
      (function () {
        var gr = document.getElementById("fleet-git-remote-row");
        if (gr) {
          gr.setAttribute("data-fleet-git-sha-state", __fleetLocalGitSha ? "present" : "missing");
        }
      })();
      __fleetSelfUpdateConfigured = !!(meta.self_update && meta.self_update.configured);
      if (!__fleetRemoteGitTimerStarted) {
        __fleetRemoteGitTimerStarted = true;
        setTimeout(function () {
          checkRemoteAgainstGitHub();
        }, 1200);
        setInterval(function () {
          checkRemoteAgainstGitHub();
        }, REMOTE_GIT_POLL_MS);
      }
      var wrap = document.getElementById("fleet-forge-console-wrap");
      var link = document.getElementById("fleet-forge-console");
      var integ = meta.integrations || {};
      var fc = integ.forge_console_url;
      if (wrap && link && fc) {
        link.href = fc;
        wrap.classList.remove("d-none");
      } else if (wrap) {
        wrap.classList.add("d-none");
      }

      if (!window.__fleetApplyRootHintOnce) {
        window.__fleetApplyRootHintOnce = true;
        var rootIn = document.getElementById("fleet-new-svc-root");
        var hint = integ.suggested_forge_llm_compose_root;
        if (rootIn && hint && !String(rootIn.value || "").trim()) {
          rootIn.value = String(hint);
        }
      }

      applySelfUpdateMeta(meta.self_update || {});

      renderManagedServices(integ);
      loadContainerTypesOnce();

      var host = data.host || {};
      var hid =
        String(host.platform || "") +
        "|" +
        String(host.cpus != null ? host.cpus : "") +
        "|" +
        String(host.python || "");
      if (hid !== chartHostIdentity) {
        chartHostIdentity = hid;
        chartBuf = [];
        orchBuf = [];
      }
      await refreshTelemetryChartsFromDb(host, integ.orchestration);
      paintOrchestrationHeader(integ.orchestration);

      document.getElementById("fleet-tiles").innerHTML = renderTiles(
        host,
        meta.energy_ledger_kwh || null,
        meta.cooldown_summary || null
      );
      applyKpiTileAnims(host);
      pushFleetTrendSample(host);
      refreshChartYHint();

      var bs = data.jobs_by_status || {};
      var keys = Object.keys(bs).sort();
      document.getElementById("by-status").innerHTML = keys.length
        ? keys.map(function (k) { return "<div class=\"fleet-stat\"><b>" + esc(bs[k]) + "</b>" + esc(k) + "</div>"; }).join("")
        : "<span class=\"text-body-secondary\">No jobs yet.</span>";

      var act = data.active_workers || [];
      document.getElementById("active").innerHTML = act.length
        ? "<div class=\"table-responsive\"><table class=\"table table-sm table-bordered mb-0\"><thead><tr><th>PID</th><th>Job</th><th>Session</th><th class=\"text-body-secondary small\">Command (abbrev.)</th></tr></thead><tbody>" +
          act.map(function (w) {
            var ap = String(w.argv_preview || "");
            if (ap.length > 96) ap = ap.slice(0, 94) + "…";
            return (
              "<tr><td class=\"fleet-mono small\">" +
              esc(w.pid) +
              "</td><td><code class=\"fleet-mono small\">" +
              esc(String(w.job_id || "").slice(0, 12)) +
              (String(w.job_id || "").length > 12 ? "…" : "") +
              "</code></td><td class=\"small\">" +
              esc(w.session_id || "—") +
              "</td><td class=\"fleet-mono small text-body-secondary\" title=\"" +
              esc(w.argv_preview || "") +
              "\">" +
              esc(ap) +
              "</td></tr>"
            );
          }).join("") + "</tbody></table></div>"
        : "<span class=\"text-body-secondary\">No subprocesses running.</span>";

      var rows = data.jobs_recent || [];
      document.getElementById("rows").innerHTML = rows.length
        ? rows.map(function (j) {
            var oid = jobOutcomeHuman(j);
            var title = j.workload_title || "Job";
            var shortId = j.id_short || (j.id ? String(j.id).slice(0, 10) + (String(j.id).length > 10 ? "…" : "") : "—");
            return (
              "<tr>" +
              "<td class=\"text-nowrap\">" +
              statusPill(j.status) +
              "</td><td><div class=\"fw-medium\">" +
              esc(title) +
              "</div><div class=\"text-body-secondary small\">Id <code class=\"fleet-mono\">" +
              esc(shortId) +
              "</code></div></td><td class=\"small text-body-secondary text-nowrap\">" +
              esc(fmtTime(j.updated)) +
              "</td><td><span class=\"" +
              oid.cls +
              "\">" +
              esc(oid.text) +
              "</span></td><td class=\"text-end\"><button type=\"button\" class=\"btn btn-sm btn-outline-secondary fleet-job-detail-btn\" data-job-id=\"" +
              esc(j.id) +
              "\">Details</button></td></tr>"
            );
          }).join("")
        : "<tr><td colspan=\"5\" class=\"text-body-secondary\">No jobs recorded.</td></tr>";

      renderFleetJobsPager(data, rows);

      return true;
    }
    async function loadSnapshot() {
      var data = await fetchAdminSnapshot();
      if (!data) return false;
      return applySnapshotData(data);
    }
    function scheduleNext() {
      nextFire = Date.now() + POLL_MS;
    }

    function tick() {
      var ms = Math.max(0, nextFire - Date.now());
      if (ms <= 0) {
        loadSnapshot().then(function () { scheduleNext(); });
      }
    }
    async function forgeSvcPost(path, okText) {
      setErr("");
      var m = document.getElementById("fleet-svc-action-msg");
      if (m) m.textContent = "…";
      try {
        var res = await fetch(path, {
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
        if (m) {
          if (res.ok && j.ok) m.textContent = okText;
          else m.textContent = "HTTP " + res.status + " — " + esc(String(j.error || j.detail || res.statusText || ""));
        }
      } catch (e) {
        if (m) m.textContent = esc(String(e));
      }
      loadSnapshot().then(function () { scheduleNext(); });
    }
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.getAttribute) return;
      var detBtn = t.closest ? t.closest(".fleet-job-detail-btn") : null;
      if (detBtn && detBtn.getAttribute) {
        ev.preventDefault();
        var jid = detBtn.getAttribute("data-job-id");
        if (jid) void openFleetJobDetail(jid);
        return;
      }
      var prevPg = t.closest ? t.closest(".fleet-jobs-page-prev") : null;
      if (prevPg && !prevPg.disabled) {
        ev.preventDefault();
        fleetJobsOffset = Math.max(0, fleetJobsOffset - fleetJobsPageSize);
        void loadSnapshot().then(scheduleNext);
        return;
      }
      var nextPg = t.closest ? t.closest(".fleet-jobs-page-next") : null;
      if (nextPg && !nextPg.disabled) {
        ev.preventDefault();
        fleetJobsOffset += fleetJobsPageSize;
        void loadSnapshot().then(scheduleNext);
        return;
      }
    });
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.getAttribute) return;
      if (t.classList.contains("fleet-svc-start")) {
        var sid = t.getAttribute("data-svc-id");
        if (sid) forgeSvcPost("/v1/container-services/" + encodeURIComponent(sid) + "/start", "start sent for " + sid);
      } else if (t.classList.contains("fleet-svc-stop")) {
        var sid2 = t.getAttribute("data-svc-id");
        if (sid2) forgeSvcPost("/v1/container-services/" + encodeURIComponent(sid2) + "/stop", "stop sent for " + sid2);
      }
    });
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.getAttribute) return;
      if (t.id === "fleet-type-add-btn") {
        ev.preventDefault();
        openFleetTypeModal("add");
      } else if (t.id === "fleet-types-reload-btn") {
        ev.preventDefault();
        __fleetTypesLoaded = false;
        void loadContainerTypesOnce(true);
      } else if (t.id === "fleet-req-template-add-btn") {
        ev.preventDefault();
        openFleetReqTemplateModal(-1);
      } else if (t.id === "fleet-req-templates-reload-btn") {
        ev.preventDefault();
        void loadRequirementTemplatesOnce(true);
      } else if (t.id === "fleet-req-templates-save-btn") {
        ev.preventDefault();
        void (async function () {
          var msg = document.getElementById("fleet-requirement-templates-editor-msg");
          if (!__fleetReqTemplatesDoc || typeof __fleetReqTemplatesDoc !== "object") {
            if (msg) msg.textContent = "Nothing to save.";
            return;
          }
          try {
            var res = await fetch("/v1/container-templates", {
              method: "PUT",
              headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
              body: JSON.stringify(__fleetReqTemplatesDoc),
            });
            var j = {};
            try {
              j = await res.json();
            } catch (_e) {
              j = {};
            }
            if (msg) msg.textContent = res.ok && j.ok ? "Saved requirement_templates.json." : "HTTP " + res.status + " — " + esc(String(j.error || ""));
            if (res.ok && j.ok) renderFleetReqTemplatesTable(j);
          } catch (e) {
            if (msg) msg.textContent = esc(String(e));
          }
        })();
      } else if (t.closest && t.closest("#fleet-template-build-btn")) {
        ev.preventDefault();
        void (async function () {
          var out = document.getElementById("fleet-template-build-result");
          var inp = document.getElementById("fleet-build-req-ids");
          var raw = (inp && inp.value ? inp.value : "").trim();
          var ids = raw
            ? raw.split(",").map(function (x) {
                return x.trim().toLowerCase();
              }).filter(Boolean)
            : [];
          if (!ids.length) {
            if (out) out.textContent = "Enter at least one requirement slug.";
            return;
          }
          try {
            var res = await fetch("/v1/container-templates/build", {
              method: "POST",
              headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
              body: JSON.stringify({ requirement_ids: ids }),
            });
            var j = {};
            try {
              j = await res.json();
            } catch (_e) {
              j = {};
            }
            if (out) out.textContent = JSON.stringify(j).slice(0, 1200);
          } catch (e) {
            if (out) out.textContent = esc(String(e));
          }
        })();
      } else if (t.classList.contains("fleet-type-edit")) {
        ev.preventDefault();
        var ftid = t.getAttribute("data-type-id");
        if (ftid) openFleetTypeModal("edit", ftid);
      } else if (t.classList.contains("fleet-type-del")) {
        ev.preventDefault();
        var dtid = t.getAttribute("data-type-id");
        if (!dtid || t.disabled) return;
        if (!window.confirm("Delete container type " + dtid + "?")) return;
        void (async function () {
          try {
            var res = await fetch("/v1/container-types/" + encodeURIComponent(dtid), {
              method: "DELETE",
              headers: authHeaders(),
            });
            var j = {};
            try {
              j = await res.json();
            } catch (_e) {
              j = {};
            }
            if (res.ok && j.ok) {
              __fleetTypesLoaded = false;
              await loadContainerTypesOnce(true);
            } else {
              setErr("Delete type: HTTP " + res.status + " — " + esc(String(j.error || "")));
            }
          } catch (e) {
            setErr(esc(String(e)));
          }
        })();
      } else if (t.classList.contains("fleet-req-edit")) {
        ev.preventDefault();
        var ix = parseInt(t.getAttribute("data-req-idx") || "-1", 10);
        if (!isNaN(ix)) openFleetReqTemplateModal(ix);
      } else if (t.classList.contains("fleet-req-del")) {
        ev.preventDefault();
        var ix2 = parseInt(t.getAttribute("data-req-idx") || "-1", 10);
        if (isNaN(ix2) || !__fleetReqTemplatesDoc || !Array.isArray(__fleetReqTemplatesDoc.templates)) return;
        if (!window.confirm("Remove this template row from the editor (save to persist)?")) return;
        __fleetReqTemplatesDoc.templates.splice(ix2, 1);
        renderFleetReqTemplatesTable({ ok: true, version: __fleetReqTemplatesDoc.version, templates: __fleetReqTemplatesDoc.templates });
      }
    });
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.getAttribute) return;
      if (t.id === "fleet-header-git-update-btn" || (t.closest && t.closest("#fleet-header-git-update-btn"))) {
        ev.preventDefault();
        doGitSelfUpdate();
      } else if (t.classList && t.classList.contains("fleet-power-open-diag")) {
        ev.preventDefault();
        openFleetPowerDiagModal();
      }
    });
    var addForm = document.getElementById("fleet-add-service-form");
    if (addForm) {
      addForm.addEventListener("submit", async function (ev) {
        ev.preventDefault();
        setErr("");
        var msg = document.getElementById("fleet-add-service-msg");
        if (msg) msg.textContent = "";
        var idEl = document.getElementById("fleet-new-svc-id");
        var rootEl = document.getElementById("fleet-new-svc-root");
        var sid = (idEl && idEl.value ? idEl.value : "").trim().toLowerCase();
        var root = (rootEl && rootEl.value ? rootEl.value : "").trim();
        var overlays = [];
        document.querySelectorAll(".fleet-svc-overlay:checked").forEach(function (c) {
          overlays.push(c.value);
        });
        if (!root) {
          if (msg) msg.textContent = "Enter the Forge LLM directory path (folder with compose.yaml).";
          return;
        }
        var payload = {
          type_id: "forge_llm",
          compose_root: root,
          compose_files: overlays,
        };
        if (sid) {
          payload.id = sid;
        }
        try {
          var res = await fetch("/v1/container-services", {
            method: "POST",
            headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
            body: JSON.stringify(payload),
          });
          var j = {};
          try {
            j = await res.json();
          } catch (_e) {
            j = {};
          }
          if (msg) {
            if (res.ok && j.ok) {
              var createdId = j.service && j.service.id ? String(j.service.id) : sid || "—";
              msg.textContent = "Registered service " + createdId + ".";
            } else {
              msg.textContent = "HTTP " + res.status + " — " + esc(String(j.error || j.detail || ""));
            }
          }
          if (res.ok && j.ok) {
            if (rootEl) rootEl.value = "";
            if (idEl) idEl.value = "";
          }
        } catch (e) {
          if (msg) msg.textContent = esc(String(e));
        }
        loadSnapshot().then(function () { scheduleNext(); });
      });
    }
    var fleetTypeSaveBtn = document.getElementById("fleet-type-edit-save");
    if (fleetTypeSaveBtn) {
      fleetTypeSaveBtn.addEventListener("click", async function () {
        var err = document.getElementById("fleet-type-edit-err");
        if (err) {
          err.textContent = "";
          err.classList.add("d-none");
        }
        var idEl = document.getElementById("fleet-type-field-id");
        var catEl = document.getElementById("fleet-type-field-category");
        var cclEl = document.getElementById("fleet-type-field-cclass");
        var titleEl = document.getElementById("fleet-type-field-title");
        var notesEl = document.getElementById("fleet-type-field-notes");
        var reqEl = document.getElementById("fleet-type-field-req");
        var capA = document.getElementById("fleet-type-cap-admin");
        var capApi = document.getElementById("fleet-type-cap-api");
        var capDr = document.getElementById("fleet-type-cap-docker");
        var payload = {
          id: (idEl && idEl.value ? idEl.value : "").trim().toLowerCase(),
          category_id: catEl ? catEl.value : "job",
          container_class: (cclEl && cclEl.value ? cclEl.value : "").trim().toLowerCase(),
          title: (titleEl && titleEl.value ? titleEl.value : "").trim(),
          notes: notesEl && notesEl.value ? notesEl.value : "",
        };
        var rq = (reqEl && reqEl.value ? reqEl.value : "")
          .split(",")
          .map(function (x) {
            return x.trim().toLowerCase();
          })
          .filter(Boolean);
        if (rq.length) payload.requirements = rq;
        if (capA && capA.checked) payload.admin_spawnable = true;
        else payload.admin_spawnable = false;
        if (capApi && capApi.checked) payload.api_manage_services = true;
        else payload.api_manage_services = false;
        if (capDr && capDr.checked) payload.allow_docker_argv_jobs = true;
        else payload.allow_docker_argv_jobs = false;
        try {
          var url =
            __fleetTypeEditMode === "add"
              ? "/v1/container-types"
              : "/v1/container-types/" + encodeURIComponent(payload.id);
          var method = __fleetTypeEditMode === "add" ? "POST" : "PUT";
          var res = await fetch(url, {
            method: method,
            headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
            body: JSON.stringify(payload),
          });
          var j = {};
          try {
            j = await res.json();
          } catch (_e) {
            j = {};
          }
          if (!res.ok || !j.ok) {
            if (err) {
              err.textContent = esc(String(j.error || j.detail || res.status));
              err.classList.remove("d-none");
            }
            return;
          }
          var modalEl = document.getElementById("fleet-type-edit-modal");
          if (modalEl && typeof bootstrap !== "undefined" && bootstrap.Modal) {
            var mi = bootstrap.Modal.getInstance(modalEl);
            if (mi) mi.hide();
            else bootstrap.Modal.getOrCreateInstance(modalEl).hide();
          }
          __fleetTypesLoaded = false;
          await loadContainerTypesOnce(true);
        } catch (e) {
          if (err) {
            err.textContent = esc(String(e));
            err.classList.remove("d-none");
          }
        }
      });
    }
    var fleetReqSaveBtn = document.getElementById("fleet-req-edit-save");
    if (fleetReqSaveBtn) {
      fleetReqSaveBtn.addEventListener("click", function () {
        var err = document.getElementById("fleet-req-edit-err");
        if (err) {
          err.textContent = "";
          err.classList.add("d-none");
        }
        var idEl = document.getElementById("fleet-req-field-id");
        var titleEl = document.getElementById("fleet-req-field-title");
        var kindEl = document.getElementById("fleet-req-field-kind");
        var refEl = document.getElementById("fleet-req-field-ref");
        var notesEl = document.getElementById("fleet-req-field-notes");
        var row = {
          id: (idEl && idEl.value ? idEl.value : "").trim().toLowerCase(),
          title: (titleEl && titleEl.value ? titleEl.value : "").trim(),
          kind: kindEl ? kindEl.value : "dockerfile",
          ref: (refEl && refEl.value ? refEl.value : "").trim(),
          notes: notesEl && notesEl.value ? notesEl.value : "",
        };
        if (!row.id) {
          if (err) {
            err.textContent = "Template id is required.";
            err.classList.remove("d-none");
          }
          return;
        }
        var templates = __fleetReqTemplatesDoc && Array.isArray(__fleetReqTemplatesDoc.templates)
          ? __fleetReqTemplatesDoc.templates.slice()
          : [];
        if (__fleetReqEditIdx >= 0 && __fleetReqEditIdx < templates.length) {
          templates[__fleetReqEditIdx] = row;
        } else {
          var dup = false;
          for (var i = 0; i < templates.length; i++) {
            if (String((templates[i] && templates[i].id) || "") === row.id) {
              dup = true;
              templates[i] = row;
