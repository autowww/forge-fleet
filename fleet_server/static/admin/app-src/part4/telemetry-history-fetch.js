      var periods = [
        ["last_24_hours", "fleet-tel-chart-24h", "tel24h"],
        ["last_7_days", "fleet-tel-chart-7d", "tel7d"],
        ["last_1_month", "fleet-tel-chart-1mo", "tel1mo"],
        ["last_year", "fleet-tel-chart-1y", "tel1y"],
      ];
      var allRows = [];
      try {
        var docs = await Promise.all(
          periods.map(function (p) {
            return fetch(
              "/v1/telemetry?period=" + encodeURIComponent(p[0]) + "&limit=500000",
              { headers: authHeaders(), cache: "no-store" }
            ).then(function (r) {
              return r.json();
            });
          })
        );
        for (var di = 0; di < docs.length; di++) {
          var doc = docs[di];
          if (doc && doc.ok && Array.isArray(doc.samples)) {
            var part = samplesToMetricRows(doc.samples, null);
            for (var pi = 0; pi < part.length; pi++) allRows.push(part[pi]);
          }
        }
        var mergedNorm = chartNormalizeTimes(allRows);
        updateMetricMaximaFromAll(mergedNorm);
        var mm = metricMaximaLoad();
        var cw = 600;
        var ch = 138;
        for (var ui = 0; ui < periods.length; ui++) {
          var doc2 = docs[ui];
          var slice = [];
          if (doc2 && doc2.ok && Array.isArray(doc2.samples)) slice = samplesToMetricRows(doc2.samples, null);
          var box = document.getElementById(periods[ui][1]);
          var pKey = doc2 && doc2.period ? String(doc2.period) : periods[ui][0];
          renderTelemetryChartInto(box, slice, mm, cw, ch, periods[ui][2], doc2, pKey);
        }
        if (statusEl) {
          statusEl.textContent =
            "Maxima (this browser): temp " +
            (mm.tempC > 0 ? mm.tempC.toFixed(1) + " °C" : "—") +
            " · load " +
            (mm.loadPct > 0 ? Math.round(mm.loadPct) + "%" : "—") +
            " · disk (tile scale) " +
            (mm.diskUi > 0 ? Math.round(mm.diskUi) + "%" : "—");
        }
      } catch (_e) {
        if (statusEl) statusEl.textContent = "Could not load telemetry.";
      } finally {
        __fleetTelHistBusy = false;
      }
    }
