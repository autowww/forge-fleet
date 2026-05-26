  (function () {
    "use strict";
    var LS = "forgeFleetAdminToken";
    var LS_LOAD_SCALE = "forgeFleetLoadScaleMax";
    var LS_LOAD_PEAK = "forgeFleetLoadPeakPct";
    var LS_CHART_LINEAR_Y = "forgeFleetChartLinearY";
    /** JSON: { tempC, loadPct, diskUi } peaks for %-of-max series (diskUi = storage tile 0–100 scale) */
    var LS_METRIC_MAX = "forgeFleetMetricMaximaV2";
    var POLL_MS = 3000;
    /** Recent jobs table: page size and offset (passed as ``jobs_limit`` / ``jobs_offset`` on snapshot). */
    var fleetJobsPageSize = 10;
    var fleetJobsOffset = 0;
    var __fleetLocalGitSha = "";
    var __fleetSelfUpdateConfigured = false;
    /** Snapshot ``meta.self_update`` (install_profile, system_root_install_command, …). */
    var __fleetSelfUpdateMeta = null;
    /** True when GitHub master commit differs from ``ver.git_sha`` (newer code on remote). */
    var __fleetGitUpdateAvailable = false;
    var __fleetRemoteGitTimerStarted = false;
    var errEl = document.getElementById("err");
    var nextFire = Date.now();
    var chartBuf = [];
    var chartHostIdentity = null;
    var CHART_MS = 3600000;
    var MAX_CHART_RENDER = 480;
    var MAX_CHART_MODAL = 720;
    var __fleetTelHistBusy = false;
    var orchBuf = [];
    /** Latest orchestration dict for container-type cards (snapshot overrides DB tail). */
    var __fleetLastOrchestration = null;
    var TREND_MS = 20000;
    var __fleetTrendBuf = [];
    /** Stabilize disk tile background band (low/mid/high) across polls to avoid flash. */
    var __fleetDiskBandHyst = { stable: null, pend: null, streak: 0, lastTintNum: null };

    function diskBandHysteresis(rawHeatTintVal) {
      var num = rawHeatTintVal == null || isNaN(Number(rawHeatTintVal)) ? 0 : Number(rawHeatTintVal);
      var want = heat3(num);
      var h = __fleetDiskBandHyst;
      if (h.lastTintNum != null && Math.abs(num - h.lastTintNum) >= 14) {
        h.stable = want;
        h.pend = null;
        h.streak = 0;
        h.lastTintNum = num;
        return want;
      }
      h.lastTintNum = num;
      if (h.stable == null) {
        h.stable = want;
        h.pend = null;
        h.streak = 0;
        return want;
      }
      if (want === h.stable) {
        h.pend = null;
        h.streak = 0;
        return want;
      }
      if (want !== h.pend) {
        h.pend = want;
        h.streak = 1;
        return h.stable;
      }
      h.streak++;
      if (h.streak >= 2) {
        h.stable = want;
        h.pend = null;
        h.streak = 0;
        return want;
      }
      return h.stable;
    }

    function resetDiskBandHysteresis() {
      __fleetDiskBandHyst.stable = null;
      __fleetDiskBandHyst.pend = null;
      __fleetDiskBandHyst.streak = 0;
      __fleetDiskBandHyst.lastTintNum = null;
    }

    function esc(s) {
      return String(s ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function fleetA11yPickText(id) {
      var el = document.getElementById(id);
      if (!el) return "";
      var t = (el.textContent || "").replace(/\s+/g, " ").trim();
      return t;
    }

    function fleetA11yRecentJobsSummary() {
      var tbody = document.getElementById("rows");
      if (!tbody) return "";
      var lines = [];
      var trs = tbody.querySelectorAll("tr");
      var max = Math.min(trs.length, 4);
      for (var i = 0; i < max; i++) {
        var row = trs[i];
        var cells = row.querySelectorAll("td");
        if (cells.length >= 3) {
          var status = (cells[0].textContent || "").trim();
          var what = (cells[1].textContent || "").trim();
          var fin = (cells[2].textContent || "").trim();
          if (status || what) {
            lines.push("• " + status + " · " + what + (fin ? " · " + fin : ""));
          }
        } else {
          var one = (row.textContent || "").trim();
          if (one) lines.push("• " + one);
        }
      }
      return lines.join("\n");
    }

    function fillFleetA11yOverviewStubs() {
      document.querySelectorAll("[data-fleet-a11y-stub]").forEach(function (span) {
        var key = span.getAttribute("data-fleet-a11y-stub");
        var val = "";
        if (key === "version") val = fleetA11yPickText("fleet-version-line");
        else if (key === "git_remote") val = fleetA11yPickText("fleet-git-remote-row");
        else if (key === "self_update") val = fleetA11yPickText("fleet-self-update-status");
        else if (key === "tiles") val = fleetA11yPickText("fleet-tiles");
        else if (key === "job_counts") val = fleetA11yPickText("by-status");
        else if (key === "workers") val = fleetA11yPickText("active");
        else if (key === "recent_jobs") val = fleetA11yRecentJobsSummary();
        else if (key === "error_banner") val = fleetA11yPickText("err");
        else if (key === "page_heading") {
          var h = document.querySelector(".fleet-admin-title");
          val = h ? (h.textContent || "").trim() : "";
        }
        span.textContent = val || "—";
      });
    }

    function metricMaximaLoad() {
      try {
        var j = localStorage.getItem(LS_METRIC_MAX);
        if (!j) return { tempC: 0, loadPct: 0, diskUi: 0 };
        var o = JSON.parse(j);
        var diskM =
          o.diskUi != null && !isNaN(o.diskUi)
            ? Number(o.diskUi)
            : o.diskMbps != null && !isNaN(o.diskMbps)
              ? Number(o.diskMbps)
              : 0;
        return {
          tempC: o.tempC != null && !isNaN(o.tempC) ? Number(o.tempC) : 0,
          loadPct: o.loadPct != null && !isNaN(o.loadPct) ? Number(o.loadPct) : 0,
          diskUi: diskM,
        };
      } catch (_e) {
        return { tempC: 0, loadPct: 0, diskUi: 0 };
      }
    }

    function metricMaximaSave(m) {
      try {
        localStorage.setItem(LS_METRIC_MAX, JSON.stringify(m));
      } catch (_e) {
        /* ignore quota */
      }
    }

    function updateMetricMaximaFromAll(buf) {
      if (!buf || !buf.length) return;
      var m = metricMaximaLoad();
      for (var i = 0; i < buf.length; i++) {
        var r = buf[i];
        if (r.tempC != null && !isNaN(r.tempC)) m.tempC = Math.max(m.tempC || 0, Number(r.tempC));
        if (r.loadPct != null && !isNaN(r.loadPct)) m.loadPct = Math.max(m.loadPct || 0, Number(r.loadPct));
        if (r.diskUi != null && !isNaN(r.diskUi)) m.diskUi = Math.max(m.diskUi || 0, Number(r.diskUi));
      }
      metricMaximaSave(m);
    }

    /** Latest RAPL reason from the power tile (updated each snapshot); shown in the diagnostics modal. */
    var __fleetPowerDiagRaplReason = "";

    function openFleetPowerDiagModal() {
      var wrap = document.getElementById("fleet-power-diag-rapl-wrap");
      var rr = __fleetPowerDiagRaplReason || "";
      if (wrap) {
        if (rr) {
          wrap.innerHTML = '<p class="small mb-2"><strong>rapl_reason:</strong> ' + esc(rr) + "</p>";
          wrap.classList.remove("d-none");
        } else {
          wrap.innerHTML = "";
          wrap.classList.add("d-none");
        }
      }
      var el = document.getElementById("fleet-power-diag-modal");
      if (el && typeof bootstrap !== "undefined" && bootstrap.Modal) {
        bootstrap.Modal.getOrCreateInstance(el).show();
      }
    }

    function fmtTime(ts) {
      if (ts == null || ts === "") return "—";
      var d = new Date(typeof ts === "number" ? ts * 1000 : Number(ts) * 1000);
      if (isNaN(d.getTime())) return String(ts);
      return d.toLocaleString();
    }

    function heat3(p) {
      if (p == null || isNaN(p)) return "mid";
      if (p < 52) return "low";
      if (p < 80) return "mid";
      return "high";
    }

    /** 0–3: green, amber, light red, dark red (by %% bands). */
    function loadZone4(p) {
      if (p == null || isNaN(p)) return 0;
      var v = Number(p);
      if (v < 25) return 0;
      if (v < 50) return 1;
      if (v < 75) return 2;
      return 3;
    }

    /** Smooth 0–100%% bar + integer label (same easing as legacy CPU tile). */
    function makeSmoothPercentBarAnim(valueId, fillId, shellId, shellClassPrefix, mirrorPctFn) {
      var DURATION_MS = 3000;
      var raf = null;
      var startT = 0;
      var from = 0;
      var to = 0;
      var lastShown = null;
      var prefix = shellClassPrefix || "fleet-cpu-compact__shell ";

      function ease(u) {
        u = Math.max(0, Math.min(1, u));
        return u * u * (3 - 2 * u);
      }

      function applyDom(val) {
        var elV = document.getElementById(valueId);
        var elF = document.getElementById(fillId);
        var elS = document.getElementById(shellId);
        if (!elV || !elF || !elS) return false;
        var clamped = Math.min(100, Math.max(0, Number(val)));
        elV.textContent = String(Math.round(clamped)) + "%";
        elF.style.width = String(Math.round(clamped * 100) / 100) + "%";
        elS.className = prefix + "fleet-cpu-wide--z" + loadZone4(clamped);
        if (typeof mirrorPctFn === "function") mirrorPctFn(clamped);
        return true;
      }

      function interpAt(now) {
        var u = (now - startT) / DURATION_MS;
        if (u >= 1) return to;
        return from + (to - from) * ease(u);
      }

      function tick() {
        var now = performance.now();
        var u = (now - startT) / DURATION_MS;
        if (u >= 1) {
          raf = null;
          lastShown = to;
          if (!applyDom(to)) lastShown = null;
          return;
        }
        if (!applyDom(from + (to - from) * ease(u))) {
          raf = null;
          return;
        }
        raf = requestAnimationFrame(tick);
      }

      function onSnapshotTarget(targetPct) {
        if (!document.getElementById(valueId)) {
          if (raf != null) {
            cancelAnimationFrame(raf);
            raf = null;
          }
          lastShown = null;
          if (typeof mirrorPctFn === "function") mirrorPctFn(null);
          return;
        }

        var now = performance.now();
        var curFromAnim = raf != null ? interpAt(now) : null;

        if (raf != null) {
          cancelAnimationFrame(raf);
          raf = null;
        }

        if (targetPct == null || isNaN(targetPct)) {
          lastShown = null;
          var elV = document.getElementById(valueId);
          var elF = document.getElementById(fillId);
          var elS = document.getElementById(shellId);
          if (elV) elV.textContent = "—";
          if (elF) elF.style.width = "0%";
          if (elS) elS.className = prefix + "fleet-cpu-wide--z0";
          if (typeof mirrorPctFn === "function") mirrorPctFn(null);
          return;
        }

        if (lastShown === null) {
          lastShown = targetPct;
          from = targetPct;
          to = targetPct;
          applyDom(targetPct);
          return;
        }

        var cur = curFromAnim != null ? curFromAnim : lastShown;

        if (Math.abs(cur - targetPct) < 0.05) {
          lastShown = targetPct;
          applyDom(targetPct);
          return;
        }

        from = cur;
        to = targetPct;
        startT = performance.now();
        applyDom(from);
        raf = requestAnimationFrame(tick);
      }

      function widthForRender(suggestedPct) {
        if (suggestedPct != null && isNaN(Number(suggestedPct))) suggestedPct = null;
        if (raf != null) return interpAt(performance.now());
        if (lastShown != null) return lastShown;
        return suggestedPct != null ? Number(suggestedPct) : null;
      }

      return { onSnapshotTarget: onSnapshotTarget, widthForRender: widthForRender };
    }

    function syncLoadHeroBarFromPct(clamped) {
      var needle = document.getElementById("fleet-load-gauge-needle");
      var elHp = document.getElementById("fleet-load-hero-pct");
      if (clamped == null || isNaN(Number(clamped))) {
        if (needle) needle.setAttribute("transform", "rotate(-180 40 38)");
        if (elHp) elHp.textContent = "—";
        return;
      }
      var w = Math.min(100, Math.max(0, Number(clamped)));
      var ang = -180 + (w / 100) * 180;
      if (needle) needle.setAttribute("transform", "rotate(" + ang + " 40 38)");
      if (elHp) elHp.textContent = String(Math.round(w)) + "% · 1m";
    }

    var __fleetLoadGhostFadeRaf = null;
    function kickLoadGaugeGhost() {
      var ghost = document.getElementById("fleet-load-gauge-needle-ghost");
      var needle = document.getElementById("fleet-load-gauge-needle");
      if (!ghost || !needle) return;
      if (__fleetLoadGhostFadeRaf != null) {
        cancelAnimationFrame(__fleetLoadGhostFadeRaf);
        __fleetLoadGhostFadeRaf = null;
      }
      ghost.setAttribute("transform", needle.getAttribute("transform") || "rotate(-180 40 38)");
      ghost.setAttribute("opacity", "0.4");
      var t0 = performance.now();
      var dur = 1150;
      function fade(now) {
        var u = (now - t0) / dur;
        if (u >= 1) {
          ghost.setAttribute("opacity", "0");
          __fleetLoadGhostFadeRaf = null;
          return;
        }
        ghost.setAttribute("opacity", String(0.4 * (1 - u)));
        __fleetLoadGhostFadeRaf = requestAnimationFrame(fade);
      }
      __fleetLoadGhostFadeRaf = requestAnimationFrame(fade);
    }

    var fleetCpuAnim = makeSmoothPercentBarAnim(
      "fleet-cpu-value",
      "fleet-cpu-fill",
      "fleet-cpu-shell",
      "fleet-cpu-compact__shell "
    );
    var fleetLoad1Anim = makeSmoothPercentBarAnim(
      "fleet-load1-val",
      "fleet-load1-fill",
      "fleet-load1-shell",
      "fleet-cpu-compact__shell fleet-load-g--compact ",
      syncLoadHeroBarFromPct
    );
    var fleetLoad5Anim = makeSmoothPercentBarAnim(
      "fleet-load5-val",
      "fleet-load5-fill",
      "fleet-load5-shell",
      "fleet-cpu-compact__shell fleet-load-g--compact "
    );
    var fleetLoad15Anim = makeSmoothPercentBarAnim(
      "fleet-load15-val",
      "fleet-load15-fill",
      "fleet-load15-shell",
      "fleet-cpu-compact__shell fleet-load-g--compact "
    );
    var fleetDiskPctAnim = makeSmoothPercentBarAnim(
      "fleet-disk-pct-val",
      "fleet-disk-pct-fill",
      "fleet-disk-pct-shell",
      "fleet-cpu-compact__shell fleet-load-g--compact "
    );

    /** Smooth scalar text (MB/s, watts, etc.). */
    function makeSmoothScalarAnim(valueId, formatRoundedInt) {
      var DURATION_MS = 3000;
      var raf = null;
      var startT = 0;
      var from = 0;
      var to = 0;
      var lastShown = null;

      function ease(u) {
        u = Math.max(0, Math.min(1, u));
        return u * u * (3 - 2 * u);
      }

      function interpAt(now) {
        var u = (now - startT) / DURATION_MS;
        if (u >= 1) return to;
        return from + (to - from) * ease(u);
      }

      function tick() {
        var now = performance.now();
        var u = (now - startT) / DURATION_MS;
        if (u >= 1) {
          raf = null;
          lastShown = to;
          applyDom(to);
          return;
        }
        if (!document.getElementById(valueId)) {
          raf = null;
          return;
        }
        applyDom(from + (to - from) * ease(u));
        raf = requestAnimationFrame(tick);
      }

      function applyDom(val) {
        var el = document.getElementById(valueId);
        if (!el) return false;
        el.textContent = formatRoundedInt(Math.round(Number(val)));
        return true;
      }

      function onSnapshotTarget(target) {
        if (!document.getElementById(valueId)) {
          if (raf != null) {
            cancelAnimationFrame(raf);
            raf = null;
          }
          lastShown = null;
          return;
        }
        var curFromAnim = raf != null ? interpAt(performance.now()) : null;
        if (raf != null) {
          cancelAnimationFrame(raf);
          raf = null;
        }
        if (target == null || isNaN(target)) {
          lastShown = null;
          var el = document.getElementById(valueId);
          if (el) el.textContent = "—";
          return;
        }
        if (lastShown === null) {
          lastShown = target;
          from = target;
          to = target;
          applyDom(target);
          return;
        }
        var cur = curFromAnim != null ? curFromAnim : lastShown;
        if (Math.abs(cur - target) < 0.05) {
          lastShown = target;
          applyDom(target);
          return;
        }
        from = cur;
        to = target;
        startT = performance.now();
        applyDom(from);
        raf = requestAnimationFrame(tick);
      }

      function widthForRender(suggested) {
        if (suggested != null && isNaN(Number(suggested))) suggested = null;
        if (raf != null) return interpAt(performance.now());
        if (lastShown != null) return lastShown;
        return suggested != null ? Number(suggested) : null;
      }

      return { onSnapshotTarget: onSnapshotTarget, widthForRender: widthForRender };
    }

    var fleetDiskMbpsAnim = makeSmoothScalarAnim("fleet-disk-mbps-val", function (n) {
      return String(n) + " MB/s";
    });
    var fleetPowerWAnim = makeSmoothScalarAnim("fleet-power-val", function (n) {
      return String(n) + " W";
    });
    var fleetGpuNvAnim = makeSmoothScalarAnim("fleet-gpu-nv-val", function (n) {
      return String(n) + "%";
    });
    var fleetGpuAmAnim = makeSmoothScalarAnim("fleet-gpu-am-val", function (n) {
      return String(n) + "%";
    });
    var fleetGpuIrAnim = makeSmoothScalarAnim("fleet-gpu-ir-val", function (n) {
      return String(n) + "% est.";
    });

    /** RAM %% + optional thin bar + quarter bank heights (eased like CPU). */
    var fleetMemAnim = (function () {
      var DURATION_MS = 3000;
      var raf = null;
      var startT = 0;
      var from = 0;
      var to = 0;
      var lastShown = null;

      function ease(u) {
        u = Math.max(0, Math.min(1, u));
        return u * u * (3 - 2 * u);
      }

      function interpAt(now) {
        var u = (now - startT) / DURATION_MS;
        if (u >= 1) return to;
        return from + (to - from) * ease(u);
      }

      function applyDom(val) {
        var elV = document.getElementById("fleet-mem-val");
        var elF = document.getElementById("fleet-mem-bar-fill");
        var elS = document.getElementById("fleet-mem-bar-shell");
        if (!elV) return false;
        var clamped = Math.min(100, Math.max(0, Number(val)));
        elV.textContent = String(Math.round(clamped)) + "%";
        if (elF && elS) {
          elF.style.width = String(Math.round(clamped * 100) / 100) + "%";
          elS.className =
            "fleet-cpu-compact__shell fleet-mem-pct-stack__shell fleet-cpu-wide--z" + loadZone4(clamped);
        }
        var fills = memQuarterFills(clamped);
        for (var bi = 0; bi < 4; bi++) {
          var bf = document.getElementById("fleet-mem-bank-fill-" + bi);
          if (bf) bf.style.height = String(Math.round(fills[bi])) + "%";
        }
        return true;
      }

      function tick() {
        var now = performance.now();
        var u = (now - startT) / DURATION_MS;
        if (u >= 1) {
          raf = null;
          lastShown = to;
          if (!applyDom(to)) lastShown = null;
          return;
        }
        if (!document.getElementById("fleet-mem-val")) {
          raf = null;
          return;
        }
        if (!applyDom(from + (to - from) * ease(u))) {
          raf = null;
          return;
        }
        raf = requestAnimationFrame(tick);
      }

      function onSnapshotTarget(targetPct) {
        if (!document.getElementById("fleet-mem-val")) {
          if (raf != null) {
            cancelAnimationFrame(raf);
            raf = null;
          }
          lastShown = null;
          return;
        }
        var curFromAnim = raf != null ? interpAt(performance.now()) : null;
        if (raf != null) {
          cancelAnimationFrame(raf);
          raf = null;
        }
        if (targetPct == null || isNaN(targetPct)) {
          lastShown = null;
          var elV = document.getElementById("fleet-mem-val");
          if (elV) elV.textContent = "—";
          var elF = document.getElementById("fleet-mem-bar-fill");
          var elS = document.getElementById("fleet-mem-bar-shell");
          if (elF) elF.style.width = "0%";
          if (elS)
            elS.className =
              "fleet-cpu-compact__shell fleet-mem-pct-stack__shell fleet-cpu-wide--z0";
          for (var bi = 0; bi < 4; bi++) {
            var bf = document.getElementById("fleet-mem-bank-fill-" + bi);
            if (bf) bf.style.height = "0%";
          }
          return;
        }
        if (lastShown === null) {
          lastShown = targetPct;
          from = targetPct;
          to = targetPct;
          applyDom(targetPct);
          return;
        }
        var cur = curFromAnim != null ? curFromAnim : lastShown;
        if (Math.abs(cur - targetPct) < 0.05) {
          lastShown = targetPct;
          applyDom(targetPct);
          return;
        }
        from = cur;
        to = targetPct;
        startT = performance.now();
        applyDom(from);
        raf = requestAnimationFrame(tick);
      }

      function widthForRender(suggestedPct) {
        if (suggestedPct != null && isNaN(Number(suggestedPct))) suggestedPct = null;
        if (raf != null) return interpAt(performance.now());
        if (lastShown != null) return lastShown;
        return suggestedPct != null ? Number(suggestedPct) : null;
      }

      return { onSnapshotTarget: onSnapshotTarget, widthForRender: widthForRender };
    })();

    function cpuPct(host) {
      var p = host.cpu_usage_pct;
      if (p == null || isNaN(Number(p))) return null;
      return Math.round(Number(p));
    }

    function memQuarterFills(usedPct) {
      var p = usedPct == null || isNaN(usedPct) ? 0 : Math.min(100, Math.max(0, Number(usedPct)));
      var out = [];
      for (var i = 0; i < 4; i++) {
        var lo = i * 25;
        var hi = (i + 1) * 25;
        var h = 0;
        if (p > lo) {
          h = p >= hi ? 100 : (100 * (p - lo)) / 25;
        }
        out.push(h);
      }
      return out;
    }

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
