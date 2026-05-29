    /**
     * Load CPU/RAM + orchestration chart series from ``telemetry_samples`` via GET /v1/telemetry,
     * then append one **live** point from the current snapshot so the right edge updates every
     * poll (~3s). DB rows alone are sparse (``FLEET_TELEMETRY_INTERVAL_S``, default 60s).
     */
    async function refreshTelemetryChartsFromDb(host, snapshotOrch) {
      chartBuf = [];
      orchBuf = [];
      try {
        var res = await fetch("/v1/telemetry?period=last_1_hour&limit=100000", {
          headers: authHeaders(),
          cache: "no-store",
        });
        if (!res.ok) {
          appendLiveTelemetryTail(host, snapshotOrch);
          renderFleetChart();
          renderOrchestrationChart();
          return;
        }
        var doc = await res.json();
        if (!doc.ok || !Array.isArray(doc.samples)) {
          appendLiveTelemetryTail(host, snapshotOrch);
          renderFleetChart();
          renderOrchestrationChart();
          return;
        }
        var now = Date.now();
        var tCut = now - CHART_MS;
        var lastOrch = null;
        for (var i = 0; i < doc.samples.length; i++) {
          var sample = doc.samples[i];
          if (!sample) continue;
          var tsMs = Number(sample.ts) * 1000;
          if (isNaN(tsMs) || tsMs < tCut) continue;
          var h = sample.host && typeof sample.host === "object" ? sample.host : {};
          var met = hostMetricsForChart(h);
          chartBuf.push({
            t: tsMs,
            cpu: met.cpu,
            mem: met.mem,
            tempC: met.tempC,
            loadPct: met.loadPct,
            diskUi: met.diskUi,
          });
          var orch = sample.orchestration;
          var sc = orchestrationScalars(orch && typeof orch === "object" ? orch : null);
          orchBuf.push({ t: tsMs, managed: sc.managed, jobs: sc.jobs });
          if (orch && typeof orch === "object") lastOrch = orch;
        }
        if (lastOrch) __fleetLastOrchestration = lastOrch;
      } catch (_e) {
        /* network / parse */
      }
      appendLiveTelemetryTail(host, snapshotOrch);
      renderFleetChart();
      renderOrchestrationChart();
    }

    /** Right-edge point from current ``/v1/admin/snapshot`` so charts move between DB writes. */
    function appendLiveTelemetryTail(host, snapshotOrch) {
      var nowT = Date.now();
      if (host && typeof host === "object") {
        var met = hostMetricsForChart(host);
        chartBuf.push({
          t: nowT,
          cpu: met.cpu,
          mem: met.mem,
          tempC: met.tempC,
          loadPct: met.loadPct,
          diskUi: met.diskUi,
        });
      }
      var orch = snapshotOrch && typeof snapshotOrch === "object" ? snapshotOrch : __fleetLastOrchestration;
      var sc = orchestrationScalars(orch);
      orchBuf.push({ t: nowT, managed: sc.managed, jobs: sc.jobs });
    }
