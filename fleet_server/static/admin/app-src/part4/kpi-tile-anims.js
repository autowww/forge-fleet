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
