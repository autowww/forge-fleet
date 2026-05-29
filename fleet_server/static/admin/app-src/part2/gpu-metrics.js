    function maxList(arr, key) {
      var m = null;
      if (!arr) return null;
      arr.forEach(function (o) {
        var v = o[key];
        if (v != null && !isNaN(v)) m = m == null ? v : Math.max(m, v);
      });
      return m;
    }

    function maxNvUtil(g) {
      return g && g.nvidia && g.nvidia.available ? maxList(g.nvidia.devices, "utilization_pct") : null;
    }

    function maxAmdUtil(g) {
      var a = 0;
      var ok = false;
      if (g && g.amdgpu_sysfs && g.amdgpu_sysfs.available && g.amdgpu_sysfs.devices) {
        var m = maxList(g.amdgpu_sysfs.devices, "utilization_pct");
        if (m != null) { a = Math.max(a, m); ok = true; }
      }
      if (g && g.rocm && g.rocm.available && g.rocm.devices) {
        var r = maxList(g.rocm.devices, "utilization_pct");
        if (r != null) { a = Math.max(a, r); ok = true; }
      }
      return ok ? a : null;
    }

    function maxIntelUtil(g) {
      return g && g.intel_drm_est && g.intel_drm_est.available ? maxList(g.intel_drm_est.devices, "utilization_pct_est") : null;
    }

    function maxNvVramPct(g) {
      return g && g.nvidia && g.nvidia.available ? maxList(g.nvidia.devices, "memory_used_pct") : null;
    }

    function gpuNvidiaHasDevices(g) {
      return !!(
        g &&
        g.nvidia &&
        g.nvidia.available === true &&
        Array.isArray(g.nvidia.devices) &&
        g.nvidia.devices.length > 0
      );
    }
    function gpuAmdHasDevices(g) {
      var a =
        g &&
        g.amdgpu_sysfs &&
        g.amdgpu_sysfs.available === true &&
        Array.isArray(g.amdgpu_sysfs.devices) &&
        g.amdgpu_sysfs.devices.length > 0;
      var r =
        g &&
        g.rocm &&
        g.rocm.available === true &&
        Array.isArray(g.rocm.devices) &&
        g.rocm.devices.length > 0;
      return !!(a || r);
    }
    function gpuIntelHasDevices(g) {
      return !!(
        g &&
        g.intel_drm_est &&
        g.intel_drm_est.available === true &&
        Array.isArray(g.intel_drm_est.devices) &&
        g.intel_drm_est.devices.length > 0
      );
    }

    function tileMemRow(label, pct) {
      if (pct == null || isNaN(pct)) {
        return "<div class=\"fleet-tile__mem\">" + esc(label) + " —</div>";
      }
      var v = Math.round(Number(pct));
      return "<div class=\"fleet-tile__mem\">" + esc(label) + " " + esc(v) + "%</div>";
    }
