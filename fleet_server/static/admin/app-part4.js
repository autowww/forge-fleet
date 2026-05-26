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

    function refreshChartYHint() {
      var el = document.getElementById("fleet-chart-y-hint");
      if (!el) return;
      var base =
        "Older left · recent right · SQLite history + live snapshot tail each refresh · ";
      el.textContent =
        base + (chartLinearYEnabled() ? "Y linear 0–100%" : "Y scale 0–1–10–50–100");
    }

    function orchestrationScalars(orch) {
      if (!orch || typeof orch !== "object") return { managed: 0, jobs: 0 };
      var bt = orch.by_type_id;
      var managed = 0;
      if (bt && bt.forge_llm && bt.forge_llm.services_running != null) {
        managed = Number(bt.forge_llm.services_running) || 0;
      }
      var jb = orch.job_running_by_container_class || {};
      var jobs = 0;
      Object.keys(jb).forEach(function (k) {
        jobs += Number(jb[k]) || 0;
      });
      return { managed: managed, jobs: jobs };
    }

    function renderOrchestrationChart() {
      var el = document.getElementById("fleet-orch-chart");
      if (!el) return;
      if (!orchBuf.length) {
        el.innerHTML =
          "<svg class=\"fleet-chart-svg\" xmlns=\"http://www.w3.org/2000/svg\" width=\"100%\" height=\"100%\" viewBox=\"0 0 600 88\"><text x=\"32\" y=\"44\" fill=\"currentColor\" opacity=\"0.45\" font-size=\"11\">No workload history in SQLite yet (telemetry_samples).</text></svg>";
        return;
      }
      var w = 600;
      var h = 88;
      var padL = 32;
      var padR = 8;
      var padT = 6;
      var padB = 12;
      var iw = w - padL - padR;
      var ih = h - padT - padB;
      var n = orchBuf.length;
      var tMin = orchBuf[0].t;
      var tMax = orchBuf[n - 1].t;
      var span = Math.max(1, tMax - tMin);
      var maxV = 1;
      for (var i = 0; i < n; i++) {
        maxV = Math.max(maxV, Number(orchBuf[i].managed) || 0, Number(orchBuf[i].jobs) || 0);
      }
      maxV = Math.ceil(maxV * 1.08) || 1;
      function yFor(v) {
        var vv = Math.min(maxV, Math.max(0, Number(v)));
        return padT + ih - (vv / maxV) * ih;
      }
      function xFor(i) {
        var ti = orchBuf[i].t;
        return padL + ((ti - tMin) / span) * iw;
      }
      var ptsM = [];
      var ptsJ = [];
      for (var j = 0; j < n; j++) {
        var xj = xFor(j);
        ptsM.push({ x: xj, y: yFor(orchBuf[j].managed) });
        ptsJ.push({ x: xj, y: yFor(orchBuf[j].jobs) });
      }
      var dM;
      var dJ;
      if (n < 2) {
        var ym = yFor(orchBuf[0].managed);
        var yj = yFor(orchBuf[0].jobs);
        dM = "M " + padL + " " + ym + " L " + (padL + iw) + " " + ym;
        dJ = "M " + padL + " " + yj + " L " + (padL + iw) + " " + yj;
      } else {
        dM = chartSmoothPathD(ptsM);
        dJ = chartSmoothPathD(ptsJ);
      }
      var svg =
        "<svg class=\"fleet-chart-svg\" xmlns=\"http://www.w3.org/2000/svg\" width=\"100%\" height=\"100%\" preserveAspectRatio=\"none\" viewBox=\"0 0 " +
        w +
        " " +
        h +
        "\">" +
        "<text x=\"" +
        padL +
        "\" y=\"" +
        (padT + 10) +
        "\" fill=\"currentColor\" opacity=\"0.42\" font-size=\"9\">0–" +
        esc(String(maxV)) +
        " (count)</text>" +
        "<path fill=\"none\" stroke=\"#34d399\" stroke-width=\"2\" stroke-linejoin=\"round\" d=\"" +
        esc(dM) +
        "\"/>" +
        "<path fill=\"none\" stroke=\"#38bdf8\" stroke-width=\"2\" stroke-linejoin=\"round\" d=\"" +
        esc(dJ) +
        "\"/>" +
        "</svg>";
      el.innerHTML = svg;
    }

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

    function formatCooldownS(sec) {
      var s = sec != null && !isNaN(Number(sec)) ? Number(sec) : 0;
      if (s <= 0) return "0s";
      if (s < 60) return Math.round(s * 10) / 10 + "s";
      var m = Math.floor(s / 60);
      var r = s - m * 60;
      if (s < 3600) {
        return m + "m" + (r >= 0.5 ? " " + Math.round(r) + "s" : "");
      }
      var h = Math.floor(s / 3600);
      var s2 = s - h * 3600;
      var m2 = Math.floor(s2 / 60);
      return h + "h" + (m2 ? " " + m2 + "m" : "");
    }

    /** LLM thermal throttle waits (SQLite), same preset keys as ``cooldown_summary`` meta — not which LLM host is configured. */
    function renderCooldownTile(cs) {
      if (!cs || typeof cs !== "object") return "";
      var td = cs.today && typeof cs.today === "object" ? cs.today : null;
      var tw = cs.this_week && typeof cs.this_week === "object" ? cs.this_week : null;
      var tm = cs.this_month && typeof cs.this_month === "object" ? cs.this_month : null;
      var ty = cs.this_year && typeof cs.this_year === "object" ? cs.this_year : null;
      var all = cs.since_first && typeof cs.since_first === "object" ? cs.since_first : null;
      if (!td && !tw && !tm && !ty && !all) return "";
      var todayS = td && td.total_cooldown_s != null && !isNaN(Number(td.total_cooldown_s)) ? Number(td.total_cooldown_s) : 0;
      var evTo = td && td.event_count != null ? Number(td.event_count) : 0;
      /* ~90 min cumulative wait today → full “hot” band */
      var heatIn = Math.min(100, Math.max(0, (todayS / 5400) * 100));
      var hz = heat3(heatIn);
      var cls = "fleet-tile fleet-tile--cooldown-" + hz;
      var weekS = tw && tw.total_cooldown_s != null ? Number(tw.total_cooldown_s) : 0;
      var monthS = tm && tm.total_cooldown_s != null ? Number(tm.total_cooldown_s) : 0;
      var yearS = ty && ty.total_cooldown_s != null ? Number(ty.total_cooldown_s) : 0;
      var allS = all && all.total_cooldown_s != null ? Number(all.total_cooldown_s) : 0;
      var hintParts = [];
      if (tw)
        hintParts.push("Week " + esc(formatCooldownS(weekS)));
      if (tm)
        hintParts.push("Mo " + esc(formatCooldownS(monthS)));
      if (ty)
        hintParts.push("Yr " + esc(formatCooldownS(yearS)));
      if (all)
        hintParts.push("All " + esc(formatCooldownS(allS)));
      var hint = hintParts.length
        ? hintParts.join(" · ")
        : "SQLite · workers’ LLM sleep (not Granite URL)";
      var mem =
        evTo > 0
          ? esc(String(evTo)) + " " + (evTo === 1 ? "wait" : "waits") + " today"
          : "No waits today";
      return (
        '<div class="' +
        cls +
        '">' +
        '<div class="fleet-tile__brand">' +
        tileMark(MARK_COOLDOWN, "LLM throttle waits") +
        '</div><div class="fleet-tile__value fleet-mono">' +
        esc(formatCooldownS(todayS)) +
        '</div><div class="fleet-tile__mem">' +
        mem +
        '</div><div class="fleet-tile__hint">' +
        hint +
        "</div></div>"
      );
    }

    function renderTiles(host, energyLedger, cooldownSummary) {
      var g = host.gpu || {};
      var memHost = host.memory || {};
      var ramPct = memHost.used_pct != null ? Number(memHost.used_pct) : null;
      if (ramPct != null && isNaN(ramPct)) ramPct = null;

      var lm = hostLoadForUi(host);
      var loadIsApprox = !!(lm && lm.approx);
      var dkPre = diskAgg(host);
      var diskHasTput =
        dkPre.ioAgg &&
        dkPre.ioAgg.total_mbps != null &&
        !isNaN(Number(dkPre.ioAgg.total_mbps));
      var diskTrendPct = diskPrimaryPct(dkPre);

      var tCpu = trendClassFor("cpu", cpuPct(host));
      var tRam =
        memHost.used_pct != null && !isNaN(Number(memHost.used_pct))
          ? trendClassFor("ram", Number(memHost.used_pct))
          : "";
      var tLoad = lm != null && lm.pct1 != null && !isNaN(lm.pct1) ? trendClassFor("load1", lm.pct1) : "";
      var tDisk = diskTrendPct != null ? trendClassFor("disk", diskTrendPct) : "";

      function loadGaugeRow(label, idBase, pctRaw) {
        var p = pctRaw != null && !isNaN(pctRaw) ? Number(pctRaw) : null;
        var anim =
          idBase === "1" ? fleetLoad1Anim : idBase === "5" ? fleetLoad5Anim : fleetLoad15Anim;
        var disp = p != null ? anim.widthForRender(p) : null;
        var w = disp != null ? Math.min(100, Math.max(0, Number(disp))) : 0;
        var z = loadZone4(w);
        var wBar = esc(String(Math.round(w * 100) / 100));
        var vTxt = p != null && !isNaN(p) ? esc(String(Math.round(w))) + "%" : "—";
        return (
          '<div class="fleet-load-g-row">' +
          '<span class="fleet-load-g-label">' +
          esc(label) +
          '</span><div class="fleet-load-g-barflex"><div id="fleet-load' +
          idBase +
          '-shell" class="fleet-cpu-compact__shell fleet-load-g--compact fleet-cpu-wide--z' +
          z +
          '">' +
          '<div class="fleet-cpu-wide__track"></div>' +
          '<div id="fleet-load' +
          idBase +
          '-fill" class="fleet-cpu-wide__fill" style="width:' +
          wBar +
          '%"></div></div></div><span id="fleet-load' +
          idBase +
          '-val" class="fleet-load-g-val fleet-mono">' +
          vTxt +
          "</span></div>"
        );
      }

      var loadTile = "";
      if (lm) {
        mergeLoadPeakPct(Math.round(lm.pct1));
        var loadHeat = heat3(Math.max(lm.pct1, lm.pct5, lm.pct15));
        var loadFoot = loadIsApprox
          ? '<div class="fleet-tile__mem fleet-load-inline fleet-mono">L ' +
            esc(String(lm.l1)) +
            " · " +
            esc(String(lm.l5)) +
            " · " +
            esc(String(lm.l15)) +
            '</div><div class="fleet-tile__fine">Approx. % using divisor n=' +
            esc(String(lm.cpus)) +
            " (CPU count missing or invalid)</div>"
          : '<div class="fleet-tile__mem fleet-load-inline fleet-mono">L ' +
            esc(String(lm.l1)) +
            " · " +
            esc(String(lm.l5)) +
            " · " +
            esc(String(lm.l15)) +
            "</div>";
        var w1Hero = fleetLoad1Anim.widthForRender(Number(lm.pct1));
        var w1p = w1Hero != null && !isNaN(w1Hero) ? Math.min(100, Math.max(0, Number(w1Hero))) : Math.min(100, Math.max(0, Number(lm.pct1)));
        loadTile =
          '<div class="fleet-tile fleet-tile--load-' +
          loadHeat +
          " fleet-load-split" +
          tLoad +
          '">' +
          '<div class="fleet-tile__brand">' +
          tileMark(MARK_LOAD, "System load") +
          '</div><div class="fleet-load-hero-stack">' +
          '<div class="fleet-load-hero-row">' +
          '<div class="fleet-load-hero-left">' +
          '<div class="fleet-tile__value fleet-mono" id="fleet-load-hero-l1">' +
          esc(fmtLoadAvg1m(lm.l1)) +
          '</div><div class="fleet-tile__fine fleet-mono" id="fleet-load-hero-pct">' +
          esc(String(Math.round(w1p))) +
          '% · 1m</div></div>' +
          '<div class="fleet-load-gauge-wrap" aria-hidden="true">' +
          '<svg class="fleet-load-gauge-svg" viewBox="0 0 80 44" xmlns="http://www.w3.org/2000/svg">' +
          '<path class="fleet-load-gauge-track" d="M 12 38 A 28 28 0 0 1 68 38" fill="none" stroke-linecap="round"/>' +
          '<line id="fleet-load-gauge-needle-ghost" class="fleet-load-gauge-needle-ghost" x1="40" y1="38" x2="68" y2="38" stroke-linecap="round" transform="rotate(-180 40 38)" opacity="0"/>' +
          '<line id="fleet-load-gauge-needle" class="fleet-load-gauge-needle-line" x1="40" y1="38" x2="68" y2="38" stroke-linecap="round" transform="rotate(-180 40 38)"/>' +
          "</svg></div></div></div>" +
          '<div class="fleet-load-gauges">' +
          loadGaugeRow("1m", "1", lm.pct1) +
          loadGaugeRow("5m", "5", lm.pct5) +
          loadGaugeRow("15m", "15", lm.pct15) +
          "</div>" +
          loadFoot +
          "</div>";
      } else {
        loadTile =
          '<div class="fleet-tile fleet-tile--inactive fleet-load-split">' +
          '<div class="fleet-tile__brand">' +
          tileMark(MARK_LOAD, "System load") +
          '</div><div class="fleet-tile__value fleet-mono">—</div>' +
          '<div class="fleet-load-gauges">' +
          loadGaugeRow("1m", "1", null) +
          loadGaugeRow("5m", "5", null) +
          loadGaugeRow("15m", "15", null) +
          "</div>" +
          '<div class="fleet-tile__mem">Load averages unavailable</div></div>';
      }

      var memTile = "";
      if (ramPct != null) {
        var dispM = fleetMemAnim.widthForRender(ramPct);
        var wMem = dispM != null && !isNaN(dispM) ? Math.min(100, Math.max(0, Number(dispM))) : Math.min(100, Math.max(0, Number(ramPct)));
        var mz = loadZone4(wMem);
        var fills = memQuarterFills(wMem);
        var banks = "";
        for (var bi = 0; bi < 4; bi++) {
          var fh = Math.round(fills[bi]);
          banks +=
            '<div class="fleet-mem-bank" title="RAM quarter ' +
            (bi + 1) +
            ' of 4">' +
            '<div id="fleet-mem-bank-fill-' +
            bi +
            '" class="fleet-mem-bank__fill" style="height:' +
            esc(String(fh)) +
            '%"></div></div>';
        }
        var gbt = memHost.total_kb != null ? Math.round(memHost.total_kb / 1024 / 1024) : null;
        var memSub =
          gbt != null
            ? '<div class="fleet-tile__mem">' + esc(String(gbt)) + " GiB total</div>"
            : '<div class="fleet-tile__mem">RAM</div>';
        var wBarM = esc(String(Math.round(wMem * 100) / 100));
        memTile =
          '<div class="fleet-tile fleet-tile--mem-' +
          heat3(wMem) +
          " fleet-mem-banks-tile fleet-mem-banks--z" +
          mz +
          tRam +
          '">' +
          '<div class="fleet-tile__brand">' +
          tileMark(MARK_RAM, "Memory") +
          '</div><div class="fleet-mem-pct-stack">' +
          '<div class="fleet-tile__value fleet-mono" id="fleet-mem-val">' +
          esc(String(Math.round(wMem))) +
          "%</div>" +
          '<div id="fleet-mem-bar-shell" class="fleet-cpu-compact__shell fleet-mem-pct-stack__shell fleet-cpu-wide--z' +
          mz +
          '">' +
          '<div class="fleet-cpu-wide__track"></div>' +
          '<div id="fleet-mem-bar-fill" class="fleet-cpu-wide__fill" style="width:' +
          wBarM +
          '%"></div></div></div>' +
          memSub +
          '<div class="fleet-mem-banks">' +
          banks +
          "</div></div>";
      } else {
        memTile = "";
      }

      var dk = dkPre;
      var diskTile = "";
      if (!dk.has) {
        resetDiskBandHysteresis();
        diskTile = "";
      } else {
        var dTint = diskBandHysteresis(dk.heatTintVal);
        var dcls = "fleet-tile fleet-tile--disk-" + dTint + tDisk;
        var hasValidTput =
          dk.ioAgg &&
          dk.ioAgg.total_mbps != null &&
          !isNaN(Number(dk.ioAgg.total_mbps));
        var dFine = "";
        var primPct = diskPrimaryPct(dk);
        var heroMbpsOnly = hasValidTput && primPct == null;
        var diskHeroHtml = "";
        if (heroMbpsOnly) {
          var mb = fleetDiskMbpsAnim.widthForRender(Number(dk.ioAgg.total_mbps));
          var wm = mb != null && !isNaN(mb) ? Math.round(mb) : Math.round(Number(dk.ioAgg.total_mbps));
          diskHeroHtml =
            '<div class="fleet-disk-stack"><div class="fleet-tile__value fleet-mono" id="fleet-disk-mbps-val">' +
            esc(String(wm)) +
            " MB/s</div></div>";
        } else if (primPct != null) {
          var bp = fleetDiskPctAnim.widthForRender(primPct);
          var wP = bp != null && !isNaN(bp) ? Math.min(100, Math.max(0, Number(bp))) : Math.min(100, Math.max(0, Number(primPct)));
          var zP = loadZone4(wP);
          var wBarP = esc(String(Math.round(wP * 100) / 100));
          diskHeroHtml =
            '<div class="fleet-disk-stack">' +
            '<div class="fleet-tile__value fleet-mono" id="fleet-disk-pct-val">' +
            esc(String(Math.round(wP))) +
            "%</div>" +
            '<div id="fleet-disk-pct-shell" class="fleet-cpu-compact__shell fleet-load-g--compact fleet-cpu-wide--z' +
            zP +
            '">' +
            '<div class="fleet-cpu-wide__track"></div>' +
            '<div id="fleet-disk-pct-fill" class="fleet-cpu-wide__fill" style="width:' +
            wBarP +
            '%"></div></div></div>';
          if (dk.maxU != null && (dk.busy != null || dk.ioAgg)) {
            dFine =
              '<div class="fleet-tile__fine">Fullest mount about ' +
              esc(String(Math.round(Number(dk.maxU)))) +
              "% used (disk space)</div>";
          }
        } else {
          diskHeroHtml = '<div class="fleet-tile__value fleet-mono">—</div>';
        }
        var memLabel =
          dk.busy != null ? "I/O" : dk.maxU != null ? "Space" : "I/O";
        var dSub = '<div class="fleet-tile__mem">' + memLabel + "</div>";
        var dHint =
          dk.ioAgg && dk.ioAgg.total_mbps != null && !isNaN(Number(dk.ioAgg.total_mbps))
            ? esc(String(Math.round(Number(dk.ioAgg.total_mbps)))) + " MB/s"
            : "— MB/s";
        diskTile =
          "<div class=\"" +
          dcls +
          "\"><div class=\"fleet-tile__brand\">" +
          tileMark(MARK_DISK, "Storage") +
          "</div>" +
          diskHeroHtml +
          dFine +
          dSub +
          "<div class=\"fleet-tile__hint\">" +
          dHint +
          "</div></div>";
      }

      var nv = maxNvUtil(g);
      var nvVram = maxNvVramPct(g);
      var nvHas = gpuNvidiaHasDevices(g);
      var am = maxAmdUtil(g);
      var amHas = gpuAmdHasDevices(g);
      var ir = maxIntelUtil(g);
      var irHas = gpuIntelHasDevices(g);

      var tNv = nv != null && !isNaN(nv) ? trendClassFor("nv", nv) : "";
      var tAm = am != null && !isNaN(am) ? trendClassFor("am", am) : "";
      var tIr = ir != null && !isNaN(ir) ? trendClassFor("ir", ir) : "";

      var gpuBlock = "";
      if (!nvHas && !amHas && !irHas) {
        gpuBlock = renderGpuStubTile();
      } else {
        if (nvHas) {
          var nvh = nv == null ? 0 : nv;
          var nvc = "fleet-tile fleet-tile--nv" + (nvh < 55 ? "" : nvh < 82 ? "-mid" : "-hot") + tNv;
          gpuBlock +=
            '<div class="' +
            nvc +
            '"><div class="fleet-tile__brand">' +
            gpuLogoBrand("nvidia", "NVIDIA") +
            '</div><div class="fleet-tile__value fleet-mono">' +
            (nv != null ? esc(Math.round(nv)) + "%" : "—") +
            "</div>" +
            tileMemRow("VRAM", nvVram) +
            '<div class="fleet-tile__hint">CUDA / GL</div></div>';
        }
        if (amHas) {
          var amh = am == null ? 0 : am;
          var amc = "fleet-tile fleet-tile--amd" + (amh < 55 ? "" : amh < 82 ? "-mid" : "-hot") + tAm;
          gpuBlock +=
            '<div class="' +
            amc +
            '"><div class="fleet-tile__brand">' +
            gpuLogoBrand("amd", "AMD") +
            '</div><div class="fleet-tile__value fleet-mono">' +
            (am != null ? esc(Math.round(am)) + "%" : "—") +
            "</div>" +
            tileMemRow("VRAM", null) +
            '<div class="fleet-tile__hint">sysfs / ROCm</div></div>';
        }
        if (irHas) {
          var irh = ir == null ? 0 : ir;
          var irc = "fleet-tile fleet-tile--intel" + (irh < 55 ? "" : irh < 82 ? "-mid" : "-hot") + tIr;
          gpuBlock +=
            '<div class="' +
            irc +
            '"><div class="fleet-tile__brand">' +
            gpuLogoBrand("intel", "Intel") +
            '</div><div class="fleet-tile__value fleet-mono">' +
            (ir != null ? esc(Math.round(ir)) + "% est." : "—") +
            "</div>" +
            tileMemRow("VRAM", null) +
            '<div class="fleet-tile__hint">Engine busy Δ</div></div>';
        }
      }

      var powerTile = renderPowerTile(host, energyLedger);
      var thermalTile = renderThermalTile(host);
      var cooldownTile = renderCooldownTile(cooldownSummary);
      return (
        renderCpuCompactTile(host, tCpu) +
        thermalTile +
        memTile +
        loadTile +
        diskTile +
        powerTile +
        cooldownTile +
        gpuBlock
      );
    }

    function applyKpiTileAnims(host) {
      fleetCpuAnim.onSnapshotTarget(cpuPct(host));
      var lm = hostLoadForUi(host);
      var loadHeroL1 = document.getElementById("fleet-load-hero-l1");
      if (loadHeroL1) loadHeroL1.textContent = lm ? fmtLoadAvg1m(lm.l1) : "—";
      if (lm) {
        fleetLoad1Anim.onSnapshotTarget(lm.pct1);
        fleetLoad5Anim.onSnapshotTarget(lm.pct5);
        fleetLoad15Anim.onSnapshotTarget(lm.pct15);
        kickLoadGaugeGhost();
      } else {
        fleetLoad1Anim.onSnapshotTarget(null);
        fleetLoad5Anim.onSnapshotTarget(null);
        fleetLoad15Anim.onSnapshotTarget(null);
        syncLoadHeroBarFromPct(null);
      }
      var memHost = host.memory || {};
      var rp = memHost.used_pct != null ? Number(memHost.used_pct) : null;
      if (rp != null && !isNaN(rp)) fleetMemAnim.onSnapshotTarget(rp);
      else fleetMemAnim.onSnapshotTarget(null);

      var dk = diskAgg(host);
      if (dk && dk.has) {
        var hasTput =
          dk.ioAgg && dk.ioAgg.total_mbps != null && !isNaN(Number(dk.ioAgg.total_mbps));
        var prim = diskPrimaryPct(dk);
        if (prim != null) {
          fleetDiskPctAnim.onSnapshotTarget(prim);
        } else {
          fleetDiskPctAnim.onSnapshotTarget(null);
        }
        if (hasTput && prim == null) {
          fleetDiskMbpsAnim.onSnapshotTarget(Number(dk.ioAgg.total_mbps));
        } else {
          fleetDiskMbpsAnim.onSnapshotTarget(null);
        }
      } else {
        fleetDiskPctAnim.onSnapshotTarget(null);
        fleetDiskMbpsAnim.onSnapshotTarget(null);
      }

      fleetPowerWAnim.onSnapshotTarget(
        __fleetLastPowerTotalW != null && !isNaN(__fleetLastPowerTotalW)
          ? Number(__fleetLastPowerTotalW)
          : null
      );

      var g = host.gpu || {};
      var nv = maxNvUtil(g);
      var am = maxAmdUtil(g);
      var ir = maxIntelUtil(g);
      if (gpuNvidiaHasDevices(g)) {
        fleetGpuNvAnim.onSnapshotTarget(nv != null && !isNaN(nv) ? Number(nv) : null);
      } else fleetGpuNvAnim.onSnapshotTarget(null);
      if (gpuAmdHasDevices(g)) {
        fleetGpuAmAnim.onSnapshotTarget(am != null && !isNaN(am) ? Number(am) : null);
      } else fleetGpuAmAnim.onSnapshotTarget(null);
      if (gpuIntelHasDevices(g)) {
        fleetGpuIrAnim.onSnapshotTarget(ir != null && !isNaN(ir) ? Number(ir) : null);
      } else fleetGpuIrAnim.onSnapshotTarget(null);
