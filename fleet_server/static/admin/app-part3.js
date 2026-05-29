    /** UTC x-axis ticks and labels below the plot (returns inner SVG fragment). */
    function fleetTelemetryXAxisMarkup(windowStartMs, windowEndMs, padL, iw, axisTopY, periodKey) {
      if (windowStartMs == null || windowEndMs == null || windowEndMs <= windowStartMs) return "";
      var span = windowEndMs - windowStartMs;
      var tickCount = 7;
      var parts = [];
      var mode = "mdhm";
      if (span <= 36 * 60 * 60 * 1000) mode = "hm";
      else if (span <= 14 * 24 * 60 * 60 * 1000) mode = "mdhm";
      else mode = "md";
      for (var i = 0; i < tickCount; i++) {
        var u = tickCount <= 1 ? 0 : i / (tickCount - 1);
        var tMs = windowStartMs + u * span;
        var x = padL + u * iw;
        parts.push(
          "<line x1=\"" +
            x.toFixed(2) +
            "\" y1=\"" +
            axisTopY.toFixed(2) +
            "\" x2=\"" +
            x.toFixed(2) +
            "\" y2=\"" +
            (axisTopY + 5).toFixed(2) +
            "\" stroke=\"currentColor\" stroke-opacity=\"0.35\" stroke-width=\"1\"/>"
        );
        var label = "";
        try {
          var d = new Date(tMs);
          if (mode === "hm") {
            label = d.toLocaleString(undefined, {
              timeZone: "UTC",
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
            });
          } else if (mode === "mdhm") {
            label = d.toLocaleString(undefined, {
              timeZone: "UTC",
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
            });
          } else {
            label = d.toLocaleString(undefined, {
              timeZone: "UTC",
              year: "numeric",
              month: "short",
              day: "numeric",
            });
          }
        } catch (_e) {
          label = "";
        }
        parts.push(
          "<text x=\"" +
            x.toFixed(2) +
            "\" y=\"" +
            (axisTopY + 16).toFixed(2) +
            "\" fill=\"currentColor\" opacity=\"0.55\" font-size=\"8.5\" text-anchor=\"middle\">" +
            esc(label) +
            "</text>"
        );
      }
      return "<g class=\"fleet-tel-x-axis\" aria-hidden=\"true\">" + parts.join("") + "</g>";
    }

    /**
     * Build SVG path strings for CPU, RAM, and %%-of-max (temp, load, disk) series.
     * Optional ``windowOpts``: { windowStartMs, windowEndMs } maps x to full period (sparse data leaves gap).
     */
    function fleetTelemetryGridAndPaths(chartRows, mm, w, h, padL, padR, padT, padB, windowOpts) {
      var iw = w - padL - padR;
      var ih = h - padT - padB;
      var n = chartRows.length;
      var winS = windowOpts && windowOpts.windowStartMs != null ? Number(windowOpts.windowStartMs) : null;
      var winE = windowOpts && windowOpts.windowEndMs != null ? Number(windowOpts.windowEndMs) : null;
      var winMode = winS != null && winE != null && winE > winS;
      if (!n) {
        var gridPartsEmpty = [];
        chartTickPercents().forEach(function (tp) {
          var gy = chartPctToY(tp, padT, ih);
          gridPartsEmpty.push(
            "<line x1=\"" +
              padL +
              "\" y1=\"" +
              gy.toFixed(2) +
              "\" x2=\"" +
              (padL + iw) +
              "\" y2=\"" +
              gy.toFixed(2) +
              "\" stroke=\"currentColor\" stroke-opacity=\"0.11\" stroke-width=\"1\"/>"
          );
          gridPartsEmpty.push(
            "<text x=\"" +
              (padL - 5) +
              "\" y=\"" +
              (gy + 3).toFixed(2) +
              "\" fill=\"currentColor\" opacity=\"0.48\" font-size=\"9\" text-anchor=\"end\">" +
              tp +
              "</text>"
          );
        });
        return {
          gridInner: gridPartsEmpty.join(""),
          dCpu: "",
          dMem: "",
          dTemp: "",
          dLoad: "",
          dDisk: "",
          w: w,
          h: h,
        };
      }
      var tMin;
      var tMax;
      var span;
      if (winMode) {
        tMin = winS;
        tMax = winE;
        span = Math.max(1, tMax - tMin);
      } else {
        tMin = chartRows[0].t != null ? chartRows[0].t : 0;
        tMax = chartRows[n - 1].t != null ? chartRows[n - 1].t : tMin + 1;
        span = Math.max(1, tMax - tMin);
      }
      var xsTime = [];
      for (var xi = 0; xi < n; xi++) {
        var rw = chartRows[xi];
        var ti = rw && rw.t != null ? rw.t : tMin;
        xsTime.push(padL + ((ti - tMin) / span) * iw);
      }
      var useIdxX = false;
      if (!winMode && n >= 2) {
        var spanMs = tMax - tMin;
        var dupc = 0;
        for (var xj = 1; xj < n; xj++) {
          if (Math.abs(xsTime[xj] - xsTime[xj - 1]) < 0.6) dupc++;
        }
        if (spanMs < 2000 || dupc >= Math.max(2, Math.floor(n * 0.35))) useIdxX = true;
      }
      function xAt(i) {
        if (useIdxX) return padL + (n <= 1 ? 0 : (i / Math.max(1, n - 1)) * iw);
        return xsTime[i];
      }
      var rawC = [];
      var rawM = [];
      var rawT = [];
      var rawL = [];
      var rawD = [];
      for (var ri = 0; ri < n; ri++) {
        var rowR = chartRows[ri];
        rawC.push(rowR && rowR.cpu != null && !isNaN(rowR.cpu) ? Number(rowR.cpu) : 0);
        rawM.push(rowR && rowR.mem != null && !isNaN(rowR.mem) ? Number(rowR.mem) : 0);
        rawT.push(pctOfMaxRaw(rowR && rowR.tempC, mm.tempC));
        rawL.push(pctOfMaxRaw(rowR && rowR.loadPct, mm.loadPct));
        rawD.push(pctOfMaxRaw(rowR && rowR.diskUi, mm.diskUi));
      }
      var dCpu;
      var dMem;
      var dTemp;
      var dLoad;
      var dDisk;
      if (n === 1) {
        var yc0 = chartPctToY(rawC[0], padT, ih);
        var ym0 = chartPctToY(rawM[0], padT, ih);
        var yt0 = chartPctToY(rawT[0], padT, ih);
        var yl0 = chartPctToY(rawL[0], padT, ih);
        var yd0 = chartPctToY(rawD[0], padT, ih);
        var xFull = (padL + iw).toFixed(2);
        dCpu = "M " + padL + " " + yc0.toFixed(2) + " L " + xFull + " " + yc0.toFixed(2);
        dMem = "M " + padL + " " + ym0.toFixed(2) + " L " + xFull + " " + ym0.toFixed(2);
        dTemp = "M " + padL + " " + yt0.toFixed(2) + " L " + xFull + " " + yt0.toFixed(2);
        dLoad = "M " + padL + " " + yl0.toFixed(2) + " L " + xFull + " " + yl0.toFixed(2);
        dDisk = "M " + padL + " " + yd0.toFixed(2) + " L " + xFull + " " + yd0.toFixed(2);
      } else {
        var ptsCpu = [];
        var ptsMem = [];
        var ptsTemp = [];
        var ptsLoad = [];
        var ptsDisk = [];
        for (var i = 0; i < n; i++) {
          var xi2 = xAt(i);
          ptsCpu.push({ x: xi2, y: chartPctToY(rawC[i], padT, ih) });
          ptsMem.push({ x: xi2, y: chartPctToY(rawM[i], padT, ih) });
          ptsTemp.push({ x: xi2, y: chartPctToY(rawT[i], padT, ih) });
          ptsLoad.push({ x: xi2, y: chartPctToY(rawL[i], padT, ih) });
          ptsDisk.push({ x: xi2, y: chartPctToY(rawD[i], padT, ih) });
        }
        dCpu = chartPolylineD(ptsCpu);
        dMem = chartPolylineD(ptsMem);
        dTemp = chartPolylineD(ptsTemp);
        dLoad = chartPolylineD(ptsLoad);
        dDisk = chartPolylineD(ptsDisk);
      }
      var gridParts = [];
      chartTickPercents().forEach(function (tp) {
        var gy = chartPctToY(tp, padT, ih);
        gridParts.push(
          "<line x1=\"" +
            padL +
            "\" y1=\"" +
            gy.toFixed(2) +
            "\" x2=\"" +
            (padL + iw) +
            "\" y2=\"" +
            gy.toFixed(2) +
            "\" stroke=\"currentColor\" stroke-opacity=\"0.11\" stroke-width=\"1\"/>"
        );
        gridParts.push(
          "<text x=\"" +
            (padL - 5) +
            "\" y=\"" +
            (gy + 3).toFixed(2) +
            "\" fill=\"currentColor\" opacity=\"0.48\" font-size=\"9\" text-anchor=\"end\">" +
            tp +
            "</text>"
        );
      });
      return {
        gridInner: gridParts.join(""),
        dCpu: dCpu,
        dMem: dMem,
        dTemp: dTemp,
        dLoad: dLoad,
        dDisk: dDisk,
        w: w,
        h: h,
      };
    }

    function samplesToMetricRows(samples, tCutMs) {
      var out = [];
      var now = Date.now();
      var cut = tCutMs != null ? now - tCutMs : null;
      for (var i = 0; i < samples.length; i++) {
        var sample = samples[i];
        if (!sample) continue;
        var tsMs = Number(sample.ts) * 1000;
        if (isNaN(tsMs)) continue;
        if (cut != null && tsMs < cut) continue;
        var h = sample.host && typeof sample.host === "object" ? sample.host : {};
        var met = hostMetricsForChart(h);
        out.push({
          t: tsMs,
          cpu: met.cpu,
          mem: met.mem,
          tempC: met.tempC,
          loadPct: met.loadPct,
          diskUi: met.diskUi,
        });
      }
      return out;
    }

    function renderTelemetrySvgMarkup(gp, strokeScale, idPrefix, xAxisMarkup) {
      var sw = strokeScale != null ? strokeScale : 2;
      var swThin = Math.max(1.25, sw - 0.65);
      var p = idPrefix != null && String(idPrefix).trim() !== "" ? String(idPrefix).trim() + "-" : "";
      var xa = xAxisMarkup != null ? String(xAxisMarkup) : "";
      return (
        "<g id=\"" +
        esc(p + "fleet-chart-grid") +
        "\">" +
        gp.gridInner +
        "</g>" +
        "<path id=\"" +
        esc(p + "fleet-chart-cpu") +
        "\" fill=\"none\" stroke=\"#34d399\" stroke-width=\"" +
        sw +
        "\" stroke-linejoin=\"round\" stroke-linecap=\"round\" vector-effect=\"non-scaling-stroke\" shape-rendering=\"geometricPrecision\" d=\"" +
        esc(gp.dCpu) +
        "\"/>" +
        "<path id=\"" +
        esc(p + "fleet-chart-mem") +
        "\" fill=\"none\" stroke=\"#38bdf8\" stroke-width=\"" +
        sw +
        "\" stroke-linejoin=\"round\" stroke-linecap=\"round\" vector-effect=\"non-scaling-stroke\" shape-rendering=\"geometricPrecision\" d=\"" +
        esc(gp.dMem) +
        "\"/>" +
        "<path id=\"" +
        esc(p + "fleet-chart-temp") +
        "\" fill=\"none\" stroke=\"#fb923c\" stroke-width=\"" +
        swThin +
        "\" stroke-linejoin=\"round\" stroke-linecap=\"round\" vector-effect=\"non-scaling-stroke\" shape-rendering=\"geometricPrecision\" d=\"" +
        esc(gp.dTemp) +
        "\"/>" +
        "<path id=\"" +
        esc(p + "fleet-chart-load") +
        "\" fill=\"none\" stroke=\"#eab308\" stroke-width=\"" +
        swThin +
        "\" stroke-linejoin=\"round\" stroke-linecap=\"round\" vector-effect=\"non-scaling-stroke\" shape-rendering=\"geometricPrecision\" d=\"" +
        esc(gp.dLoad) +
        "\"/>" +
        "<path id=\"" +
        esc(p + "fleet-chart-disk") +
        "\" fill=\"none\" stroke=\"#c084fc\" stroke-width=\"" +
        swThin +
        "\" stroke-linejoin=\"round\" stroke-linecap=\"round\" vector-effect=\"non-scaling-stroke\" shape-rendering=\"geometricPrecision\" d=\"" +
        esc(gp.dDisk) +
        "\"/>" +
        xa
      );
    }

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

    function fmtWatts(w) {
      if (w == null || isNaN(Number(w)) || Number(w) < 0) return "—";
      return String(Math.round(Number(w)));
    }

    function formatLedgerKwhLine(ledger) {
      if (!ledger || ledger.total_kwh == null || isNaN(Number(ledger.total_kwh))) {
        return "No running total yet — leave this page open a little while and it may appear.";
      }
      var t = Number(ledger.total_kwh);
      var s = t < 1 ? String(Math.round(t * 1000)) + " Wh" : String(Math.round(t)) + " kWh";
      return "Electricity use logged while Fleet was watching: " + esc(s) + ".";
    }

    function formatLedgerKwhShort(ledger) {
      if (!ledger || ledger.total_kwh == null || isNaN(Number(ledger.total_kwh))) {
        return "";
      }
      var t = Number(ledger.total_kwh);
      var s = t < 1 ? String(Math.round(t * 1000)) + " Wh" : String(Math.round(t)) + " kWh";
      return "Running total: " + esc(s) + ".";
    }

    var __fleetLastPowerTotalW = null;

    function renderPowerTile(host, energyLedger) {
      __fleetLastPowerTotalW = null;
      var en = (host && host.energy) || {};
      var raplOk = en.rapl_available === true && en.rapl_package_uj != null && !isNaN(Number(en.rapl_package_uj));
      var uj = raplOk ? Number(en.rapl_package_uj) : null;
      var gpuW = en.gpu_power_draw_w_sum != null && !isNaN(Number(en.gpu_power_draw_w_sum)) ? Number(en.gpu_power_draw_w_sum) : null;
      var tMs = host && host.time_utc ? Date.parse(String(host.time_utc)) : NaN;

      var raplW = null;
      if (raplOk && uj != null && !isNaN(tMs)) {
        if (__fleetRaplPrev.uj != null && __fleetRaplPrev.tMs != null) {
          var dt = (tMs - __fleetRaplPrev.tMs) / 1000;
          if (dt >= 0.2 && dt <= 120) {
            var duj = uj - __fleetRaplPrev.uj;
            if (duj >= 0) {
              raplW = (duj / 1e6) / dt;
              if (!isFinite(raplW) || raplW < 0 || raplW > 1200) raplW = null;
            }
          }
        }
        __fleetRaplPrev.uj = uj;
        __fleetRaplPrev.tMs = tMs;
      }

      var raplInstant =
        en.rapl_instant_w != null && !isNaN(Number(en.rapl_instant_w)) && Number(en.rapl_instant_w) > 0
          ? Number(en.rapl_instant_w)
          : null;
      if (raplW == null && raplInstant != null) raplW = raplInstant;

      var totalW = null;
      if (raplW != null && gpuW != null) totalW = raplW + gpuW;
      else if (raplW != null) totalW = raplW;
      else if (gpuW != null) totalW = gpuW;

      var heroW = null;
      if (totalW != null && !isNaN(Number(totalW))) heroW = Number(totalW);
      else if (gpuW != null && !isNaN(Number(gpuW))) heroW = Number(gpuW);

      var hasSignal = totalW != null || raplOk || gpuW != null;
      var hintLine = formatLedgerKwhShort(energyLedger) || formatLedgerKwhLine(energyLedger);

      if (!hasSignal) {
        var rr = en.rapl_reason != null ? String(en.rapl_reason).trim() : "";
        __fleetPowerDiagRaplReason = rr;
        return "";
      }

      __fleetLastPowerTotalW = heroW;
      var heatIn = heroW != null ? Math.min(100, Math.max(0, (heroW / 320) * 100)) : 0;
      var pHeat = heat3(heatIn);
      var pwDisp = heroW != null && !isNaN(heroW) ? fleetPowerWAnim.widthForRender(heroW) : null;
      var wPow =
        pwDisp != null && !isNaN(pwDisp)
          ? Math.round(Number(pwDisp))
          : heroW != null && !isNaN(heroW)
            ? Math.round(Number(heroW))
            : null;
      var main =
        wPow != null
          ? '<span id="fleet-power-val" class="fleet-mono">' + esc(String(wPow)) + " W</span>"
          : '<span id="fleet-power-val" class="fleet-mono">—</span>';
      var memParts = [];
      if (raplW != null) memParts.push("Processor about " + esc(fmtWatts(raplW)) + " W");
      else if (raplOk) memParts.push("Processor: hang on — watts fill in on the next refresh");
      if (gpuW != null) memParts.push("GPU about " + esc(fmtWatts(gpuW)) + " W");
      var memLine = memParts.length ? memParts.join(" · ") : "Power draw";
      var rrOn = en.rapl_reason != null ? String(en.rapl_reason).trim() : "";
      __fleetPowerDiagRaplReason = rrOn;
      return (
        '<div class="fleet-tile fleet-tile--power-' +
        pHeat +
        '">' +
        '<div class="fleet-tile__brand">' +
        tileMark(MARK_POWER, "Power") +
        "</div>" +
        '<div class="fleet-tile__value fleet-mono">' +
        main +
        "</div>" +
        '<div class="fleet-tile__mem">' +
        esc(memLine) +
        "</div>" +
        '<div class="fleet-tile__hint">' +
        hintLine +
        "</div>" +
        '<p class="small mb-1 mt-1"><button type="button" class="btn btn-link btn-sm p-0 fleet-power-open-diag">How to see watts / diagnostics</button></p>' +
        "</div>"
      );
    }

    function renderThermalTile(host) {
      var th = (host && host.thermal) || {};
      var mc = th.max_c;
      var gn = host && host.gpu && host.gpu.nvidia;
      var gpuMax = null;
      if (gn && gn.available && gn.devices && gn.devices.length) {
        var gt = [];
        for (var gi = 0; gi < gn.devices.length; gi++) {
          var d = gn.devices[gi];
          var tt = d && d.temperature_c;
          if (tt != null && !isNaN(Number(tt))) gt.push(Number(tt));
        }
        if (gt.length) gpuMax = Math.max.apply(null, gt);
      }
      var cpuOk = mc != null && !isNaN(Number(mc));
      var gpuOk = gpuMax != null && !isNaN(Number(gpuMax));
      if (!cpuOk && !gpuOk) return "";

      var cpuV = cpuOk ? Number(mc) : null;
      var hero =
        cpuOk && gpuOk ? Math.max(cpuV, gpuMax) : cpuOk ? cpuV : gpuOk ? gpuMax : null;
      var hz = heat3(Math.min(100, Math.max(0, hero)));
      var fmt = function (x) {
        return esc(String(Math.round(Number(x) * 10) / 10));
      };

      var memLine;
      var hintLine;
      if (gpuOk) {
        var parts = [];
        if (cpuOk) parts.push("CPU " + fmt(cpuV) + "°C");
        parts.push("GPU " + fmt(gpuMax) + "°C");
        memLine = parts.join(" · ");
        hintLine =
          (cpuOk ? "Linux thermal / hwmon (CPU)" : "No CPU thermal sysfs") +
          " · NVIDIA (nvidia-smi)";
      } else {
        memLine = esc(String(th.source || "sysfs"));
        hintLine = "Linux thermal / hwmon (CPU max)";
      }

      return (
        '<div class="fleet-tile fleet-tile--mem-' +
        hz +
        '">' +
        '<div class="fleet-tile__brand">' +
        tileMark(MARK_THERMAL, "Thermal") +
        "</div>" +
        '<div class="fleet-tile__value fleet-mono">' +
        fmt(hero) +
        "°C</div>" +
        '<div class="fleet-tile__mem">' +
        memLine +
        "</div>" +
        '<div class="fleet-tile__hint">' +
        esc(hintLine) +
        "</div></div>"
      );
    }

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

    async function openFleetTelemetryHistoryModal() {
      if (__fleetTelHistBusy) return;
      var modalEl = document.getElementById("fleet-tel-history-modal");
      var statusEl = document.getElementById("fleet-tel-hist-status");
      if (!modalEl || typeof bootstrap === "undefined" || !bootstrap.Modal) return;
      __fleetTelHistBusy = true;
      if (statusEl) statusEl.textContent = "Loading…";
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
