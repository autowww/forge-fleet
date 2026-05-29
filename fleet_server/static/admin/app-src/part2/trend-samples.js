    function trendClassFor(key, current) {
      if (current == null || isNaN(Number(current))) return "";
      var target = Date.now() - TREND_MS;
      var baseVal = null;
      for (var i = __fleetTrendBuf.length - 1; i >= 0; i--) {
        if (__fleetTrendBuf[i].t <= target) {
          var v = __fleetTrendBuf[i][key];
          if (v != null && !isNaN(Number(v))) baseVal = Number(v);
          break;
        }
      }
      if (baseVal == null || isNaN(baseVal)) return "";
      var delta = Number(current) - baseVal;
      var ad = Math.abs(delta);
      if (ad <= 5) return "";
      var tier = ad <= 15 ? 1 : 2;
      if (delta > 0) return " fleet-tile--trend-heat-" + tier;
      return " fleet-tile--trend-cool-" + tier;
    }

    function pushFleetTrendSample(host) {
      var now = Date.now();
      var c = cpuPct(host);
      var ram = null;
      if (host.memory && host.memory.used_pct != null && !isNaN(Number(host.memory.used_pct))) {
        ram = Number(host.memory.used_pct);
      }
      var lm = hostLoadForUi(host);
      var l1 = lm != null && lm.pct1 != null && !isNaN(lm.pct1) ? lm.pct1 : null;
      var dk = diskAgg(host);
      var diskP = diskPrimaryPct(dk);
      var g = host.gpu || {};
      var gs = [];
      if (gpuNvidiaHasDevices(g)) {
        var nvU = maxNvUtil(g);
        if (nvU != null) gs.push(nvU);
      }
      if (gpuAmdHasDevices(g)) {
        var amU = maxAmdUtil(g);
        if (amU != null) gs.push(amU);
      }
      if (gpuIntelHasDevices(g)) {
        var irU = maxIntelUtil(g);
        if (irU != null) gs.push(irU);
      }
      var gpuM = gs.length ? Math.max.apply(null, gs) : null;
      __fleetTrendBuf.push({
        t: now,
        cpu: c != null && !isNaN(c) ? Number(c) : null,
        ram: ram,
        load1: l1,
        disk: diskP,
        gpu: gpuM,
        nv: gpuNvidiaHasDevices(g) && maxNvUtil(g) != null ? Number(maxNvUtil(g)) : null,
        am: gpuAmdHasDevices(g) && maxAmdUtil(g) != null ? Number(maxAmdUtil(g)) : null,
        ir: gpuIntelHasDevices(g) && maxIntelUtil(g) != null ? Number(maxIntelUtil(g)) : null,
      });
      var pruneBefore = now - TREND_MS - 8000;
      while (__fleetTrendBuf.length && __fleetTrendBuf[0].t < pruneBefore) {
        __fleetTrendBuf.shift();
      }
    }
