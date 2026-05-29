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
