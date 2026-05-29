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
