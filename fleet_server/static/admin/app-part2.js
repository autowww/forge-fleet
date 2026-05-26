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

    /* Tile header marks (inline SVG, currentColor from .fleet-tile__brand). */
    /* Inline SVG marks (no hotlinked images — works offline and matches tile contrast). */
    var MARK_CPU =
      "<svg class=\"fleet-tile__mark\" width=\"40\" height=\"32\" viewBox=\"0 0 40 32\" xmlns=\"http://www.w3.org/2000/svg\" role=\"img\" aria-label=\"CPU\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.55\" stroke-linejoin=\"round\"><rect x=\"8\" y=\"8\" width=\"24\" height=\"16\" rx=\"2\"/><path d=\"M12 8V5M28 8V5M12 27v-3M28 27v-3M8 14H5M8 20H5M35 14h-3M35 20h-3\"/></svg>";
    var MARK_RAM =
      "<svg class=\"fleet-tile__mark\" width=\"40\" height=\"28\" viewBox=\"0 0 40 28\" xmlns=\"http://www.w3.org/2000/svg\" aria-hidden=\"true\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"><rect x=\"5\" y=\"5\" width=\"12\" height=\"20\" rx=\"1.5\"/><rect x=\"23\" y=\"5\" width=\"12\" height=\"20\" rx=\"1.5\"/><path d=\"M9 9h4M9 13h4M9 17h4M27 9h4M27 13h4M27 17h4\"/></svg>";
    var MARK_DISK =
      "<svg class=\"fleet-tile__mark\" width=\"40\" height=\"32\" viewBox=\"0 0 40 32\" xmlns=\"http://www.w3.org/2000/svg\" aria-hidden=\"true\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.45\" stroke-linejoin=\"round\"><ellipse cx=\"20\" cy=\"11\" rx=\"13\" ry=\"5\"/><path d=\"M7 11v7c0 2.5 5.8 4.5 13 4.5S33 20.5 33 18v-7\"/><path d=\"M7 18v5c0 2.5 5.8 4.5 13 4.5S33 25.5 33 23v-5\"/></svg>";
    var MARK_POWER =
      "<svg class=\"fleet-tile__mark\" width=\"40\" height=\"40\" viewBox=\"0 0 40 40\" xmlns=\"http://www.w3.org/2000/svg\" aria-hidden=\"true\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.65\" stroke-linejoin=\"round\"><path d=\"M22 5L9 23h10l-5 18 16-22H21l1-14z\"/></svg>";
    var MARK_LOAD =
      "<svg class=\"fleet-tile__mark\" width=\"40\" height=\"32\" viewBox=\"0 0 40 32\" xmlns=\"http://www.w3.org/2000/svg\" aria-hidden=\"true\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.55\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M7 26V14M20 26V6M33 26V18\"/><path d=\"M5 26h30\" opacity=\"0.85\"/></svg>";
    var MARK_THERMAL =
      "<svg class=\"fleet-tile__mark\" width=\"40\" height=\"40\" viewBox=\"0 0 40 40\" xmlns=\"http://www.w3.org/2000/svg\" aria-hidden=\"true\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.55\" stroke-linejoin=\"round\"><path d=\"M22 7v23a6 6 0 1 1-4 0V7a2 2 0 1 1 4 0z\"/></svg>";
    var MARK_COOLDOWN =
      "<svg class=\"fleet-tile__mark\" width=\"40\" height=\"40\" viewBox=\"0 0 40 40\" xmlns=\"http://www.w3.org/2000/svg\" aria-hidden=\"true\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><circle cx=\"20\" cy=\"22\" r=\"12\"/><path d=\"M20 14v8l5 3\"/></svg>";

  var __fleetRaplPrev = { uj: null, tMs: null };

    var GPU_LOGO_BASE = "/admin/static/gpu-logos/";
    function gpuLogoImg(vendor, alt, extraClass) {
      var c = "fleet-gpu-logo" + (extraClass ? " " + extraClass : "");
      return (
        '<img class="' +
        c +
        '" src="' +
        esc(GPU_LOGO_BASE + vendor + ".png") +
        '" alt="' +
        esc(alt) +
        '" loading="lazy" width="100" height="32" />'
      );
    }
    function gpuLogoButton(vendor, alt, stub) {
      var intel = vendor === "intel";
      var cls = "fleet-gpu-logo-btn" + (stub ? " fleet-gpu-logo-btn--stub" : "") + (intel ? " fleet-gpu-logo-btn--intel" : "");
      return (
        '<span class="' +
        cls +
        '">' +
        gpuLogoImg(vendor, alt, "fleet-gpu-logo--inbtn") +
        '<span class="visually-hidden">' +
        esc(alt) +
        "</span></span>"
      );
    }
    function gpuLogoBrand(vendor, alt) {
      return '<div class="fleet-gpu-brand">' + gpuLogoButton(vendor, alt, false) + "</div>";
    }
    function renderGpuStubTile() {
      return "";
    }

    function tileMark(svg, hiddenLabel) {
      if (hiddenLabel == null || String(hiddenLabel).trim() === "") return svg;
      return svg + "<span class=\"visually-hidden\">" + esc(hiddenLabel) + "</span>";
    }

    function fmtLoadAvg1m(x) {
      if (x == null || isNaN(Number(x))) return "—";
      var n = Number(x);
      var t = Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(2);
      return String(t);
    }

    function getLoadScaleDenominator(liveCpus) {
      var c = liveCpus != null && !isNaN(Number(liveCpus)) && Number(liveCpus) > 0 ? Number(liveCpus) : 1;
      var raw = localStorage.getItem(LS_LOAD_SCALE);
      if (raw == null || String(raw).trim() === "") {
        return { den: c, saved: false, liveCpus: c };
      }
      var n = parseFloat(String(raw).trim());
      if (!isFinite(n) || n <= 0) {
        return { den: c, saved: false, liveCpus: c };
      }
      return { den: n, saved: true, liveCpus: c };
    }

    function mergeLoadPeakPct(pct) {
      if (pct == null || isNaN(pct)) return;
      var v = Math.round(Number(pct));
      var cur = parseFloat(localStorage.getItem(LS_LOAD_PEAK) || "");
      if (!isFinite(cur)) cur = 0;
      if (v > cur) localStorage.setItem(LS_LOAD_PEAK, String(v));
    }

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

    function loadMetrics(host) {
      var c = host.cpus != null ? Number(host.cpus) : null;
      var la = host.loadavg;
      if (!Array.isArray(la) || la.length < 3 || c == null || isNaN(c) || c < 1) return null;
      var l1 = Number(la[0]);
      var l5 = Number(la[1]);
      var l15 = Number(la[2]);
      if (isNaN(l1) || isNaN(l5) || isNaN(l15)) return null;
      var sc = getLoadScaleDenominator(c);
      var den = sc.den;
      return {
        l1: l1,
        l5: l5,
        l15: l15,
        cpus: c,
        scaleDen: den,
        scaleSaved: sc.saved,
        pct1: Math.min(100, Math.max(0, (100 * l1) / den)),
        pct5: Math.min(100, Math.max(0, (100 * l5) / den)),
        pct15: Math.min(100, Math.max(0, (100 * l15) / den)),
      };
    }

    /** When ``loadMetrics`` is null but ``/proc``-style loadavg exists (e.g. bad CPU count), still show bars. */
    function approxLoadMetrics(host) {
      if (loadMetrics(host) != null) return null;
      var la = host && host.loadavg;
      if (!Array.isArray(la) || la.length < 3) return null;
      var l1 = Number(la[0]);
      var l5 = Number(la[1]);
      var l15 = Number(la[2]);
      if (isNaN(l1) || isNaN(l5) || isNaN(l15)) return null;
      var c = host.cpus != null ? Number(host.cpus) : NaN;
      var den = isFinite(c) && c >= 1 ? c : 1;
      return {
        l1: l1,
        l5: l5,
        l15: l15,
        cpus: den,
        scaleDen: den,
        scaleSaved: false,
        pct1: Math.min(100, Math.max(0, (100 * l1) / den)),
        pct5: Math.min(100, Math.max(0, (100 * l5) / den)),
        pct15: Math.min(100, Math.max(0, (100 * l15) / den)),
        approx: true,
      };
    }

    function hostLoadForUi(host) {
      return loadMetrics(host) || approxLoadMetrics(host);
    }

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

    function chartLinearYEnabled() {
      try {
        return localStorage.getItem(LS_CHART_LINEAR_Y) === "1";
      } catch (_e) {
        return false;
      }
    }

    /**
     * Map 0–100%% to normalized height g in [0,1] (piecewise linear: 10 lower, 50 at 75%% band).
     * y = padT + ih - g*ih so larger g is higher on screen.
     */
    function chartPctNormG(p) {
      var u = Math.min(100, Math.max(0, Number(p)));
      var g10 = 0.38;
      if (u <= 10) return (u / 10) * g10;
      if (u <= 50) return g10 + ((u - 10) / 40) * (0.75 - g10);
      return 0.75 + ((u - 50) / 50) * 0.25;
    }

    function chartPctNormGLinear(p) {
      var u = Math.min(100, Math.max(0, Number(p)));
      return u / 100;
    }

    function chartPctToY(p, padT, ih) {
      var g = chartLinearYEnabled() ? chartPctNormGLinear(p) : chartPctNormG(p);
      return padT + ih - g * ih;
    }

    function chartTickPercents() {
      return [0, 1, 10, 50, 100];
    }

    /**
     * Downsample to ``maxPts`` targets along the visible window. Each target time ``tt``
     * takes the **nearest** raw sample (by timestamp), not linear interpolation — so past
     * vertices stay tied to real polls and do not “breathe” when new points arrive.
     */
    function chartBufResampleTime(buf, maxPts) {
      if (!buf || !buf.length) return [];
      if (buf.length <= maxPts) return buf.slice();
      var t0 = Number(buf[0].t);
      var t1 = Number(buf[buf.length - 1].t);
      var span = Math.max(1, t1 - t0);
      var out = [];
      for (var j = 0; j < maxPts; j++) {
        var u = maxPts <= 1 ? 0 : j / (maxPts - 1);
        var tt = t0 + u * span;
        var best = buf[0];
        var bestD = Math.abs(Number(buf[0].t) - tt);
        for (var i = 1; i < buf.length; i++) {
          var d = Math.abs(Number(buf[i].t) - tt);
          if (d < bestD) {
            bestD = d;
            best = buf[i];
          }
        }
        out.push({
          t: tt,
          cpu: best.cpu,
          mem: best.mem,
          tempC: best.tempC,
          loadPct: best.loadPct,
          diskUi: best.diskUi,
        });
      }
      return out;
    }

    /** Open polyline (piecewise linear) — stable under sliding windows (no spline tangents). */
    function chartPolylineD(pts) {
      if (!pts || !pts.length) return "";
      if (pts.length === 1) {
        return "M " + pts[0].x + " " + pts[0].y;
      }
      var d = "M " + pts[0].x + " " + pts[0].y;
      for (var i = 1; i < pts.length; i++) {
        d += " L " + pts[i].x + " " + pts[i].y;
      }
      return d;
    }

    /** Catmull–Rom segment → SVG cubic Bézier through points (open curve). */
    function chartSmoothPathD(pts) {
      if (!pts || pts.length < 2) return "";
      var n = pts.length;
      if (n === 2) {
        return "M " + pts[0].x + " " + pts[0].y + " L " + pts[1].x + " " + pts[1].y;
      }
      var d = "M " + pts[0].x + " " + pts[0].y;
      for (var i = 0; i < n - 1; i++) {
        var p0 = pts[Math.max(0, i - 1)];
        var p1 = pts[i];
        var p2 = pts[i + 1];
        var p3 = pts[Math.min(n - 1, i + 2)];
        var c1x = p1.x + (p2.x - p0.x) / 6;
        var c1y = p1.y + (p2.y - p0.y) / 6;
        var c2x = p2.x - (p3.x - p1.x) / 6;
        var c2y = p2.y - (p3.y - p1.y) / 6;
        d += " C " + c1x + " " + c1y + " " + c2x + " " + c2y + " " + p2.x + " " + p2.y;
      }
      return d;
    }

    /** Ensure every row has monotonic ms timestamps (fixes vertical collapse when t missing or stuck). */
    function chartNormalizeTimes(buf) {
      if (!buf || !buf.length) return [];
      var out = [];
      var lastT = null;
      for (var i = 0; i < buf.length; i++) {
        var r = buf[i];
        var t = r.t != null && !isNaN(Number(r.t)) ? Number(r.t) : null;
        if (t == null) {
          t = lastT != null ? lastT + POLL_MS : Date.now() - (buf.length - 1 - i) * POLL_MS;
        }
        if (lastT != null && t <= lastT) t = lastT + 1;
        lastT = t;
        out.push({
          t: t,
          cpu: r.cpu,
          mem: r.mem,
          tempC: r.tempC,
          loadPct: r.loadPct,
          diskUi: r.diskUi,
        });
      }
      return out;
    }

    function pctOfMaxRaw(val, maxVal) {
      if (val == null || isNaN(val)) return 0;
      var mx = maxVal != null && !isNaN(maxVal) && Number(maxVal) > 0 ? Number(maxVal) : 0;
      if (mx <= 0) return 0;
      return Math.min(100, Math.max(0, (Number(val) / mx) * 100));
    }

    function sortMetricRows(rows) {
      if (!rows || !rows.length) return [];
      return rows
        .slice()
        .sort(function (a, b) {
          return Number(a.t) - Number(b.t);
        });
    }

    /** Average numeric fields per wall-clock bucket; one row per bucket that has ≥1 sample. ``t`` = bucket center ms. */
    function averageMetricRowsIntoBuckets(rows, bucketMs, windowStartMs, windowEndMs) {
      if (!bucketMs || bucketMs <= 0 || windowEndMs <= windowStartMs) return [];
      var buckets = {};
      function addSum(bk, key, val) {
        if (val == null || isNaN(val)) return;
        if (!buckets[bk]) buckets[bk] = { sums: {}, counts: {} };
        var s = buckets[bk].sums;
        var c = buckets[bk].counts;
        s[key] = (s[key] || 0) + Number(val);
        c[key] = (c[key] || 0) + 1;
      }
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        var t = r.t != null && !isNaN(Number(r.t)) ? Number(r.t) : null;
        if (t == null || t < windowStartMs || t > windowEndMs) continue;
        var bk = Math.floor((t - windowStartMs) / bucketMs);
        var maxBk = Math.floor((windowEndMs - windowStartMs) / bucketMs);
        if (bk < 0 || bk > maxBk + 1) continue;
        addSum(bk, "cpu", r.cpu);
        addSum(bk, "mem", r.mem);
        addSum(bk, "tempC", r.tempC);
        addSum(bk, "loadPct", r.loadPct);
        addSum(bk, "diskUi", r.diskUi);
      }
      var out = [];
      var keys = Object.keys(buckets)
        .map(Number)
        .sort(function (a, b) {
          return a - b;
        });
      for (var j = 0; j < keys.length; j++) {
        var bki = keys[j];
        var B = buckets[bki];
        var sums = B.sums;
        var counts = B.counts;
        var center = windowStartMs + bki * bucketMs + bucketMs / 2;
        function avg(k) {
          var cnt = counts[k] || 0;
          if (!cnt) return null;
          return sums[k] / cnt;
        }
        out.push({
          t: center,
          cpu: avg("cpu") != null ? avg("cpu") : 0,
          mem: avg("mem") != null ? avg("mem") : 0,
          tempC: avg("tempC"),
          loadPct: avg("loadPct"),
          diskUi: avg("diskUi"),
        });
      }
      return out;
    }

    var NICE_BUCKET_MS = [
      60 * 1000,
      2 * 60 * 1000,
      3 * 60 * 1000,
      5 * 60 * 1000,
      10 * 60 * 1000,
      15 * 60 * 1000,
      20 * 60 * 1000,
      30 * 60 * 1000,
      60 * 60 * 1000,
      2 * 60 * 60 * 1000,
      3 * 60 * 60 * 1000,
      4 * 60 * 60 * 1000,
      6 * 60 * 60 * 1000,
      8 * 60 * 60 * 1000,
      12 * 60 * 60 * 1000,
      24 * 60 * 60 * 1000,
      2 * 24 * 60 * 60 * 1000,
      7 * 24 * 60 * 60 * 1000,
    ];

    function pickNiceBucketMs(windowMs, innerWidthPx) {
      var iwPx = innerWidthPx != null && innerWidthPx > 0 ? innerWidthPx : 556;
      var targetBuckets = Math.round(iwPx / 46);
      targetBuckets = Math.max(24, Math.min(160, targetBuckets));
      var ideal = windowMs / Math.max(1, targetBuckets);
      var best = NICE_BUCKET_MS[Math.floor(NICE_BUCKET_MS.length / 2)];
      var bestScore = Infinity;
      for (var i = 0; i < NICE_BUCKET_MS.length; i++) {
        var step = NICE_BUCKET_MS[i];
        var nb = windowMs / step;
        if (nb > 220 || nb < 6) continue;
        var lo = ideal * 0.65;
        var hi = ideal * 1.75;
        var score = step < lo ? lo - step : step > hi ? step - hi : Math.abs(step - ideal);
        if (score < bestScore) {
          bestScore = score;
          best = step;
        }
      }
      if (bestScore < Infinity) return best;
      for (var j = 0; j < NICE_BUCKET_MS.length; j++) {
        var st = NICE_BUCKET_MS[j];
        var nbb = windowMs / st;
        if (nbb <= 220 && nbb >= 3) return st;
      }
      return 60 * 60 * 1000;
    }

    /**
     * Prepare modal series: fixed UTC window from ``doc.window``, bucket averages (5 min for 24h; else nice step).
     */
    function buildModalChartRows(periodKey, rawRows, doc) {
      var win = doc && doc.window && typeof doc.window === "object" ? doc.window : null;
      var t0 = win && win.start_epoch != null ? Number(win.start_epoch) : NaN;
      var t1 = win && win.end_epoch != null ? Number(win.end_epoch) : NaN;
      if (!isFinite(t0) || !isFinite(t1)) {
        return { averagedRows: [], windowStartMs: null, windowEndMs: null, bucketMs: null };
      }
      var windowStartMs = t0 * 1000;
      var windowEndMs = t1 * 1000;
      var sorted = sortMetricRows(rawRows || []);
      var clipped = [];
      for (var i = 0; i < sorted.length; i++) {
        var tr = sorted[i].t;
        if (tr != null && !isNaN(Number(tr)) && Number(tr) >= windowStartMs && Number(tr) <= windowEndMs) {
