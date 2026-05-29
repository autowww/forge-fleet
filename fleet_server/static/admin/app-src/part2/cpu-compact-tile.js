    function renderCpuCompactTile(host, trendCls) {
      trendCls = trendCls || "";
      var cpuP = cpuPct(host);
      var disp =
        cpuP != null && !isNaN(cpuP) ? fleetCpuAnim.widthForRender(cpuP) : null;
      if (disp == null || isNaN(disp)) disp = cpuP != null && !isNaN(cpuP) ? Number(cpuP) : null;
      var w = disp != null ? Math.min(100, Math.max(0, Number(disp))) : 0;
      var z = loadZone4(w);
      var logC = host.cpus != null && !isNaN(Number(host.cpus)) ? Number(host.cpus) : null;
      var physC =
        host.cpu_cores_physical != null && !isNaN(Number(host.cpu_cores_physical))
          ? Number(host.cpu_cores_physical)
          : null;
      var coreStr =
        logC != null ? (physC != null ? String(logC) + "/" + String(physC) : String(logC)) : "—";
      var ghzStr =
        host.cpu_freq_mhz_avg != null && !isNaN(Number(host.cpu_freq_mhz_avg))
          ? (Number(host.cpu_freq_mhz_avg) / 1000).toFixed(1) + " GHz"
          : "—";
      var mainPct =
        cpuP != null && !isNaN(cpuP) ? esc(String(Math.round(w))) + "%" : "—";
      var wBar = esc(String(Math.round(w * 100) / 100));
      return (
        '<div class="fleet-tile fleet-cpu-compact' +
        trendCls +
        '">' +
        '<div class="fleet-tile__brand">' + tileMark(MARK_CPU, "") + "</div>" +
        '<div class="fleet-cpu-stack">' +
        '<div class="fleet-cpu-wide__value fleet-cpu-wide__value--above fleet-mono" id="fleet-cpu-value">' +
        mainPct +
        "</div>" +
        '<div id="fleet-cpu-shell" class="fleet-cpu-compact__shell fleet-cpu-wide--z' +
        z +
        '">' +
        '<div class="fleet-cpu-wide__track"></div>' +
        '<div id="fleet-cpu-fill" class="fleet-cpu-wide__fill" style="width:' +
        wBar +
        '%"></div>' +
        "</div>" +
        '<div class="fleet-cpu-wide__meta">' +
        esc(ghzStr) +
        " · Core: " +
        esc(coreStr) +
        "</div></div></div>"
      );
    }
