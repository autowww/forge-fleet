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
