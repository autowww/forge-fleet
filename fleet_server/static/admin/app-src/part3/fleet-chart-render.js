    function renderFleetChart() {
      var el = document.getElementById("fleet-load-chart");
      if (!el) return;
      var w = 600;
      var h = 108;
      var padL = 36;
      var padR = 8;
      var padT = 6;
      var padB = 14;
      var bufFull = chartNormalizeTimes(chartBuf);
      if (!bufFull.length) {
        el.innerHTML =
          "<svg class=\"fleet-chart-svg\" xmlns=\"http://www.w3.org/2000/svg\" width=\"100%\" height=\"100%\" viewBox=\"0 0 " +
          w +
          " " +
          h +
          "\"><text x=\"" +
          padL +
          "\" y=\"" +
          (h / 2) +
          "\" fill=\"currentColor\" opacity=\"0.45\" font-size=\"12\">Waiting for samples…</text></svg>";
        return;
      }
      updateMetricMaximaFromAll(bufFull);
      var mm = metricMaximaLoad();
      var chartRows = chartBufResampleTime(bufFull, MAX_CHART_RENDER);
      var gp = fleetTelemetryGridAndPaths(chartRows, mm, w, h, padL, padR, padT, padB);
      var innerMarkup = renderTelemetrySvgMarkup(gp, 2.25, "", "");
      var svg = el.querySelector("svg.fleet-chart-svg");
      if (!svg) {
        el.innerHTML =
          "<svg class=\"fleet-chart-svg\" xmlns=\"http://www.w3.org/2000/svg\" width=\"100%\" height=\"100%\" preserveAspectRatio=\"none\" viewBox=\"0 0 " +
          w +
          " " +
          h +
          "\">" +
          innerMarkup +
          "</svg>";
        return;
      }
      svg.innerHTML = innerMarkup;
      svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    }

    function renderTelemetryChartInto(el, bufLike, mm, w, h, idPrefix, doc, periodKey) {
      if (!el) return;
      var padL = 36;
      var padR = 8;
      var padT = 6;
      var padAxis = 26;
      var padBPlot = 6;
      var padB = padBPlot + padAxis;
      var iwFull = w - padL - padR;
      var rawRows = chartNormalizeTimes(bufLike || []);
      var built = buildModalChartRows(periodKey || "", rawRows, doc || {});
      var chartRows = built.averagedRows || [];
      var windowOpts =
        built.windowStartMs != null && built.windowEndMs != null
          ? { windowStartMs: built.windowStartMs, windowEndMs: built.windowEndMs }
          : null;
      var ih = Math.max(1, h - padT - padB);
      var axisTopY = padT + ih + 2;
      var xAxis =
        windowOpts && fleetTelemetryXAxisMarkup(
          built.windowStartMs,
          built.windowEndMs,
          padL,
          iwFull,
          axisTopY,
          periodKey || ""
        );
      var gp = fleetTelemetryGridAndPaths(chartRows, mm, w, h, padL, padR, padT, padB, windowOpts || undefined);
      var emptyHint =
        !chartRows.length && windowOpts
          ? "<text x=\"" +
            ((padL + iwFull) / 2).toFixed(2) +
            "\" y=\"" +
            (padT + ih / 2).toFixed(2) +
            "\" fill=\"currentColor\" opacity=\"0.42\" font-size=\"11\" text-anchor=\"middle\">No samples in this window</text>"
          : "";
      el.innerHTML =
        "<svg class=\"fleet-chart-svg\" xmlns=\"http://www.w3.org/2000/svg\" width=\"100%\" height=\"100%\" preserveAspectRatio=\"none\" viewBox=\"0 0 " +
        w +
        " " +
        h +
        "\">" +
        renderTelemetrySvgMarkup(gp, 1.85, idPrefix || "tel", (xAxis || "") + emptyHint) +
        "</svg>";
    }
