    /** Max of CPU sysfs °C and NVIDIA GPU °C when present (matches Thermal tile). */
    function hostThermalMaxC(host) {
      if (!host || typeof host !== "object") return null;
      var th = host.thermal || {};
      var mc = th.max_c;
      var gn = host.gpu && host.gpu.nvidia;
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
      if (!cpuOk && !gpuOk) return null;
      var cpuV = cpuOk ? Number(mc) : null;
      return cpuOk && gpuOk ? Math.max(cpuV, gpuMax) : cpuOk ? cpuV : gpuOk ? gpuMax : null;
    }

    /** Raw metrics for chart rows (CPU/RAM %% absolute; temp °C; load 0–100; disk = storage tile 0–100). */
    function hostMetricsForChart(h) {
      h = h && typeof h === "object" ? h : {};
      var cpuRaw = h.cpu_usage_pct;
      var cpu = cpuRaw != null && !isNaN(Number(cpuRaw)) ? Math.min(100, Math.max(0, Number(cpuRaw))) : 0;
      var memH = h.memory && typeof h.memory === "object" ? h.memory : {};
      var memRaw = memH.used_pct;
      var mem = memRaw != null && !isNaN(Number(memRaw)) ? Math.min(100, Math.max(0, Number(memRaw))) : 0;
      var tC = hostThermalMaxC(h);
      var lm = hostLoadForUi(h);
      var l1 = lm != null && lm.pct1 != null && !isNaN(lm.pct1) ? Math.min(100, Math.max(0, Number(lm.pct1))) : null;
      var dk = diskAgg(h);
      var dui = diskPrimaryPct(dk);
      return { cpu: cpu, mem: mem, tempC: tC, loadPct: l1, diskUi: dui != null && !isNaN(dui) ? Number(dui) : null };
    }
