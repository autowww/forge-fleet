    function diskAgg(host) {
      var d = (host && host.disks) || {};
      var space = d.space || [];
      var io = d.io || {};
      var maxU = null;
      var parts = [];
      for (var i = 0; i < space.length; i++) {
        var r = space[i];
        var u = r.used_pct;
        if (u != null && !isNaN(Number(u))) {
          var nu = Number(u);
          maxU = maxU == null ? nu : Math.max(maxU, nu);
          if (r.mount) parts.push(esc(String(r.mount)) + " " + esc(Math.round(nu)) + "%");
        }
      }
      var ioAgg = io && io.available === true && io.aggregated ? io.aggregated : null;
      var busy = ioAgg && ioAgg.busy_pct_est_max != null && !isNaN(ioAgg.busy_pct_est_max) ? Number(ioAgg.busy_pct_est_max) : null;
      var heatVal = 0;
      if (maxU != null) heatVal = maxU;
      if (busy != null) heatVal = Math.max(heatVal, busy);
      /* Zone tint follows the same signal as the hero number: busy when I/O is present. */
      var heatTintVal = busy != null ? busy : heatVal;
      var has = maxU != null || ioAgg != null;
      return {
        maxU: maxU,
        ioAgg: ioAgg,
        busy: busy,
        heatVal: heatVal,
        heatTintVal: heatTintVal,
        parts: parts,
        has: has,
        ioReason: (io && io.reason) || null,
      };
    }

    /** Map aggregate MB/s to 0–100 for tile bar when kernel busy%% is missing (display scale only). */
    var DISK_IO_REF_MBPS = 600;

    function diskMbpsToUiPct(mbps) {
      var m = Number(mbps);
      if (isNaN(m) || m < 0) return null;
      return Math.min(100, Math.max(0, (m / DISK_IO_REF_MBPS) * 100));
    }

    /** Hero %% for Storage: I/O busy (max) when present; else MB/s-scaled %% when I/O aggregate exists; else mount used %%. */
    function diskPrimaryPct(dk) {
      if (!dk || !dk.has) return null;
      if (dk.busy != null && !isNaN(Number(dk.busy))) return Number(dk.busy);
      if (dk.ioAgg && dk.ioAgg.total_mbps != null && !isNaN(Number(dk.ioAgg.total_mbps))) {
        var mp = diskMbpsToUiPct(dk.ioAgg.total_mbps);
        if (mp != null) return mp;
      }
      if (dk.maxU != null && !isNaN(Number(dk.maxU))) return Number(dk.maxU);
      return null;
    }
