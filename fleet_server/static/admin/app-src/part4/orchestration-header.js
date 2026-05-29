    function formatTypeTelemetry(tid, categoryId, containerClass, orch) {
      var o = orch || __fleetLastOrchestration;
      if (!o || typeof o !== "object") return "Telemetry: —";
      var bt = o.by_type_id || {};
      var jb = o.job_running_by_container_class || {};
      var row = bt[tid] || {};
      var sr = Number(row.services_running) || 0;
      var st = row.services_total != null ? Number(row.services_total) : null;
      var cc = String(containerClass || tid || "");
      var jobs = Number(jb[cc] || 0) || 0;
      var cat = String(categoryId || "");
      if (cat === "service") {
        var tot = st != null && !isNaN(st) ? String(Math.round(st)) : "—";
        return "Compose services running: " + sr + " / " + tot + " (per stack)";
      }
      if (cat === "job") {
        return "Running jobs: " + jobs + " (container_class " + cc + ")";
      }
      return "Compose services: " + sr + " · Running jobs (class " + cc + "): " + jobs;
    }

    function refreshContainerTypesTelemetry(orch) {
      var tbl = document.getElementById("fleet-container-types-table");
      if (!tbl) return;
      var cards = tbl.querySelectorAll("tr.fleet-type-card[data-fleet-type-id]");
      var src = orch || __fleetLastOrchestration;
      for (var ci = 0; ci < cards.length; ci++) {
        var card = cards[ci];
        var tid = card.getAttribute("data-fleet-type-id") || "";
        var cat = card.getAttribute("data-category-id") || "";
        var ccl = card.getAttribute("data-container-class") || "";
        var tel = card.querySelector("[data-fleet-type-tel]");
        if (tel) tel.textContent = formatTypeTelemetry(tid, cat, ccl, src);
      }
    }

    /**
     * Header text + container-type cards from live snapshot orchestration (fresher than last DB row).
     * Chart series come from ``refreshTelemetryChartsFromDb``; this only updates summary + cards.
     */
    function paintOrchestrationHeader(orch) {
      if (orch && typeof orch === "object") __fleetLastOrchestration = orch;
      var wrap = document.getElementById("fleet-orchestration-wrap");
      var sumEl = document.getElementById("fleet-orch-summary");
      if (!__fleetLastOrchestration) {
        if (wrap) wrap.classList.add("d-none");
        return;
      }
      var s = orchestrationScalars(__fleetLastOrchestration);
      if (sumEl) {
        var line1 =
          "Compose services running (forge_llm total): " +
          s.managed +
          " · Running jobs (all classes): " +
          s.jobs;
        var bt = __fleetLastOrchestration.by_type_id || {};
        var keys = Object.keys(bt).sort();
        var parts = [];
        for (var ki = 0; ki < keys.length; ki++) {
          var k = keys[ki];
          var r = bt[k] || {};
          var run = Number(r.services_running) || 0;
          var tot = r.services_total != null ? Number(r.services_total) : null;
          parts.push(
            k +
              ": " +
              run +
              "/" +
              (tot != null && !isNaN(tot) ? String(Math.round(tot)) : "—") +
              " svc"
          );
        }
        sumEl.textContent = line1 + (parts.length ? "\nPer type_id: " + parts.join(" · ") : "");
      }
      if (wrap) wrap.classList.remove("d-none");
      refreshContainerTypesTelemetry(__fleetLastOrchestration);
    }
