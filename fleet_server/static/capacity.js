/* Fleet admin — Capacity tab (disk Space Guardian + memory guardian). */
(function () {
  "use strict";

  var LS = "forgeFleetAdminToken";

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function authHeaders() {
    var t = (localStorage.getItem(LS) || "").trim();
    var h = { Accept: "application/json" };
    if (t) h.Authorization = "Bearer " + t;
    return h;
  }

  function fleetApi(path, opts) {
    opts = opts || {};
    var headers = authHeaders();
    if (opts.headers) {
      Object.keys(opts.headers).forEach(function (k) {
        headers[k] = opts.headers[k];
      });
    }
    return fetch(path, {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body != null ? opts.body : undefined,
      cache: "no-store",
    });
  }

  function isRemoteScope() {
    return !!activePeerId();
  }

  function activePeerId() {
    try {
      return (localStorage.getItem("forgeFleetActiveRemotePeer") || "").trim();
    } catch (_e) {
      return "";
    }
  }

  function scopePeerLabel() {
    var id = activePeerId();
    var sel = document.getElementById("fleet-scope-select");
    if (!id || !sel || sel.value !== id) return id;
    var opt = sel.options[sel.selectedIndex];
    return ((opt && opt.textContent) || id).trim();
  }

  function syncCapacityScope() {
    var remote = !!activePeerId();
    document.querySelectorAll(".fleet-capacity-local-only").forEach(function (el) {
      el.classList.toggle("d-none", remote);
    });
  }

  function fmtBytes(n) {
    var x = Number(n);
    if (!isFinite(x) || x < 0) return "—";
    var u = ["B", "KiB", "MiB", "GiB", "TiB"];
    var i = 0;
    while (x >= 1024 && i < u.length - 1) {
      x /= 1024;
      i += 1;
    }
    return (i === 0 ? String(Math.round(x)) : x.toFixed(1)) + " " + u[i];
  }

  function fmtDuration(sec) {
    var s = Number(sec);
    if (!isFinite(s)) return "—";
    if (s < 120) return Math.round(s) + "s";
    if (s < 7200) return Math.round(s / 60) + "m";
    return (s / 3600).toFixed(1) + "h";
  }

  function setMsg(id, text, isErr) {
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = text || "";
    el.className = "fleet-mono small mb-2 " + (isErr ? "text-danger" : "text-body-secondary");
  }

  function setBenchStatus(text, isErr) {
    var el = document.getElementById("fleet-cap-bench-status");
    if (!el) return;
    el.textContent = text || "";
    el.className = "small mb-0 mt-2 " + (isErr ? "text-danger" : "text-body-secondary");
  }

  function benchErrorText(j, statusText) {
    var err = (j && j.error) || statusText || "benchmark_failed";
    if (err === "busy") return "Host load is above the CPU count, so the benchmark was skipped.";
    if (err === "cooldown") {
      var wait = j && j.retry_after_s != null ? " Try again in " + j.retry_after_s + "s." : "";
      return "A benchmark already ran recently." + wait;
    }
    if (err === "heavy_busy") return "Another heavy Fleet request is still running.";
    if (err === "benchmark_timeout") return "The benchmark did not finish in time.";
    if (err === "benchmark_failed" && j && j.detail) return "Benchmark failed: " + j.detail;
    if (err === "not_found") return "This peer does not expose the hardware benchmark route. Upgrade it, then launch again.";
    return String(err);
  }

  function renderDisk(space) {
    var root = document.getElementById("fleet-capacity-disk-body");
    if (!root) return;
    if (!space || !space.ok) {
      root.innerHTML = '<p class="text-danger mb-0">Disk status unavailable.</p>';
      return;
    }
    var pressure = space.pressure || {};
    var last = space.last_run || {};
    var quarantine =
      space.volumes && space.volumes.quarantine ? space.volumes.quarantine : {};
    var qCount = quarantine.count != null ? quarantine.count : 0;
    var html =
      '<dl class="row small mb-3">' +
      '<dt class="col-sm-4">Guardian</dt><dd class="col-sm-8">' +
      esc(space.guardian_enabled ? "enabled" : "disabled") +
      (space.skip_reason ? " · skip: " + esc(space.skip_reason) : "") +
      "</dd>" +
      '<dt class="col-sm-4">Pressure</dt><dd class="col-sm-8">' +
      esc(pressure.under_pressure ? "under pressure" : "ok") +
      "</dd>" +
      '<dt class="col-sm-4">Last run</dt><dd class="col-sm-8">' +
      esc(last.started_at || "—") +
      " · freed " +
      esc(fmtBytes(last.bytes_freed_total || 0)) +
      "</dd>" +
      '<dt class="col-sm-4">Next run</dt><dd class="col-sm-8">' +
      (space.next_run_in_s != null ? esc(String(space.next_run_in_s) + "s") : "—") +
      "</dd>" +
      '<dt class="col-sm-4">Quarantine</dt><dd class="col-sm-8">' +
      esc(String(qCount)) +
      " volume(s)</dd></dl>";
    var orphans = (space.volumes && space.volumes.orphan_candidates) || [];
    if (orphans.length) {
      html += '<div class="small mb-2"><strong>Orphan candidates</strong><ul class="mb-0">';
      orphans.slice(0, 12).forEach(function (v) {
        html += "<li class=\"fleet-mono\">" + esc(v.name || v.volume_name || JSON.stringify(v)) + "</li>";
      });
      html += "</ul></div>";
    }
    var qvols = quarantine.volumes || [];
    if (qvols.length) {
      html += '<div class="small mb-2"><strong>Quarantined volumes</strong><ul class="mb-0">';
      qvols.slice(0, 12).forEach(function (v) {
        var vn = v.volume_name || v.name || "";
        html +=
          "<li class=\"fleet-mono\">" +
          esc(vn) +
          " · " +
          esc(v.state || "") +
          (v.state === "approval_required"
            ? ' <button type="button" class="btn btn-sm btn-outline-danger py-0 fleet-cap-approve-vol" data-volume="' +
              esc(vn) +
              '">Approve delete</button>'
            : "") +
          "</li>";
      });
      html += "</ul></div>";
    }
    root.innerHTML = html;
    root.querySelectorAll(".fleet-cap-approve-vol").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var vol = btn.getAttribute("data-volume") || "";
        if (!vol) return;
        fleetApi("/v1/admin/space/approve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ volume_name: vol }),
        })
          .then(function (r) {
            return r.json().then(function (j) {
              if (!r.ok) throw new Error(j.detail || j.error || r.statusText);
              return j;
            });
          })
          .then(function () {
            setMsg("fleet-capacity-msg", "Approved volume " + vol);
            refreshCapacity();
          })
          .catch(function (e) {
            setMsg("fleet-capacity-msg", String(e), true);
          });
      });
    });
  }

  function renderMemory(mem, policy) {
    var root = document.getElementById("fleet-capacity-memory-body");
    if (!root) return;
    if (!mem || !mem.ok) {
      root.innerHTML = '<p class="text-danger mb-0">Memory status unavailable.</p>';
      return;
    }
    var pr = mem.pressure || {};
    var gpu = mem.gpu_summary || {};
    var html =
      '<dl class="row small mb-3">' +
      '<dt class="col-sm-4">Available RAM</dt><dd class="col-sm-8">' +
      fmtBytes(pr.available_bytes) +
      " (floor " +
      fmtBytes(pr.floor_bytes) +
      ")" +
      "</dd>" +
      '<dt class="col-sm-4">Pressure</dt><dd class="col-sm-8">' +
      esc(pr.under_pressure ? "under floor" : "ok") +
      "</dd>" +
      '<dt class="col-sm-4">Apply stops</dt><dd class="col-sm-8">' +
      esc(mem.apply_stops ? "on" : "off (observe)") +
      "</dd>" +
      '<dt class="col-sm-4">GPU</dt><dd class="col-sm-8">' +
      (gpu.nvidia_available ? "NVML ok" : esc(gpu.nvidia_reason || "unavailable")) +
      "</dd></dl>";
    html += '<p class="small fw-semibold mb-1">Services</p><div class="table-responsive"><table class="table table-sm table-striped small"><thead><tr>' +
      "<th>Id</th><th>Class</th><th>Running</th><th>Idle</th></tr></thead><tbody>";
    (mem.services || []).forEach(function (row) {
      html +=
        "<tr><td class=\"fleet-mono\">" +
        esc(row.id) +
        "</td><td>" +
        esc(row.class) +
        "</td><td>" +
        esc(row.running ? "yes" : "no") +
        "</td><td>" +
        esc(fmtDuration(row.idle_seconds)) +
        "</td></tr>";
    });
    (mem.cold_targets || []).forEach(function (row) {
      html +=
        "<tr><td class=\"fleet-mono\">" +
        esc(row.id) +
        "</td><td>cold</td><td>" +
        esc(row.running ? "yes" : "no") +
        "</td><td>" +
        esc(fmtDuration(row.idle_seconds)) +
        "</td></tr>";
    });
    html += "</tbody></table></div>";
    if (mem.plan && mem.plan.length) {
      html += '<p class="small fw-semibold mb-1">Dry-run plan (would stop)</p><ul class="small fleet-mono">';
      mem.plan.forEach(function (p) {
        html += "<li>" + esc(p.id || p.unit) + " — " + esc(p.reason) + "</li>";
      });
      html += "</ul>";
    } else {
      html += '<p class="small text-body-secondary mb-0">No idle services in the stop plan.</p>';
    }
    root.innerHTML = html;

    var pol = policy && policy.policy ? policy.policy : policy;
    if (pol && pol.memory) {
      var m = pol.memory;
      var spaceEn = document.getElementById("fleet-cap-space-enabled");
      var memEn = document.getElementById("fleet-cap-memory-enabled");
      var apply = document.getElementById("fleet-cap-apply-stops");
      var floor = document.getElementById("fleet-cap-floor-gib");
      var coldH = document.getElementById("fleet-cap-cold-hours");
      var warmH = document.getElementById("fleet-cap-warm-hours");
      if (spaceEn && pol.space) {
        spaceEn.checked = pol.space.enabled !== false;
      }
      if (memEn) memEn.checked = !!m.enabled;
      if (apply) apply.checked = !!m.apply_stops;
      if (floor) floor.value = m.free_ram_floor_gib != null ? m.free_ram_floor_gib : 16;
      if (coldH) coldH.value = m.cold_idle_hours != null ? m.cold_idle_hours : 2;
      if (warmH) warmH.value = m.warm_idle_hours != null ? m.warm_idle_hours : 6;
    }
  }

  function fmtRate(mbps) {
    var n = Number(mbps);
    if (!isFinite(n) || n < 0) return "—";
    if (n >= 1000) return (n / 1000).toFixed(1) + " GB/s";
    return Math.round(n) + " MB/s";
  }

  function fmtGb(gb) {
    var n = Number(gb);
    if (!isFinite(n) || n < 0) return "—";
    return fmtBytes(n * 1e9);
  }

  function hasNumeric(v) {
    if (v === null || v === undefined || v === "") return false;
    var n = Number(v);
    return isFinite(n);
  }

  function rateOrDash(n) {
    if (!hasNumeric(n)) return "—";
    return Number(n).toFixed(2);
  }

  function scoreCell(n) {
    if (!hasNumeric(n)) return "—";
    return String(Math.round(Number(n)));
  }

  function renderMesh(profile, links) {
    var root = document.getElementById("fleet-capacity-mesh-body");
    if (!root) return;
    var hw = profile && profile.hardware ? profile.hardware : {};
    var threads = Number(hw.logical_cpus);
    var cores = Number(hw.physical_cpus);
    var cpuLine = "—";
    if (isFinite(cores) && cores > 0 && isFinite(threads) && threads > cores) {
      cpuLine = cores + " cores, " + threads + " threads";
    } else if (isFinite(threads) && threads > 0) {
      cpuLine = threads + (threads === 1 ? " core" : " cores");
    }
    if (isFinite(threads) && threads > 0 && cpuLine.indexOf("threads") < 0) {
      cpuLine += " · " + threads + " hardware threads";
    }
    var memTotal = hw.memory_total_kb != null ? fmtBytes(Number(hw.memory_total_kb) * 1024) : "—";
    var memFree = hw.memory_available_kb != null ? fmtBytes(Number(hw.memory_available_kb) * 1024) : "";
    var memLine = memFree && memTotal !== "—" ? memFree + " free of " + memTotal : memTotal;
    var disk = hw.disk && typeof hw.disk === "object" ? hw.disk : null;
    var diskLine = "—";
    if (disk && disk.total_gb != null) {
      diskLine = disk.free_gb != null
        ? fmtGb(disk.free_gb) + " free of " + fmtGb(disk.total_gb)
        : fmtGb(disk.total_gb);
    }
    var html =
      "<p class=\"small fw-semibold mb-1\">" +
      esc(activePeerId() ? "On " + scopePeerLabel() : "On this host") +
      "</p>" +
      "<dl class=\"row mb-2\">" +
      "<dt class=\"col-4\">CPU</dt><dd class=\"col-8\">" + esc(cpuLine) + "</dd>" +
      "<dt class=\"col-4\">Memory</dt><dd class=\"col-8\">" + esc(memLine) + "</dd>" +
      "<dt class=\"col-4\">Disk</dt><dd class=\"col-8\">" + esc(diskLine) + "</dd>" +
      "</dl>";
    var edges = links && links.edges ? links.edges : [];
    if (!edges.length) {
      html += "<p class=\"mb-0\">No peer link samples yet.</p>";
    } else {
      html += "<ul class=\"mb-0\">";
      edges.forEach(function (e) {
        var st = e.stats_1h || {};
        var mbps = st.throughput_mbps_avg != null ? st.throughput_mbps_avg : "—";
        var rtt = st.rtt_ms_avg != null ? st.rtt_ms_avg : "—";
        html +=
          "<li><span class=\"fleet-mono\">" +
          esc(e.peer_id) +
          "</span>: ~" +
          esc(mbps) +
          " Mb/s, RTT " +
          esc(rtt) +
          " ms (1h avg)</li>";
      });
      html += "</ul>";
    }
    root.innerHTML = html;
  }

  function renderPeerBench(profile) {
    var root = document.getElementById("fleet-bench-peer");
    if (!root) return;
    var hw = profile && profile.hardware ? profile.hardware : {};
    var bench = profile && profile.benchmark ? profile.benchmark : {};
    var timings = bench.timings && typeof bench.timings === "object" ? bench.timings : {};
    var mark = bench.fleet_mark != null ? bench.fleet_mark : "—";
    var measured = "";
    if (profile && profile.measured_at) {
      try {
        measured = new Date(profile.measured_at * 1000).toLocaleString();
      } catch (_e) {
        measured = "";
      }
    }
    var scoresCurrent = Number(bench.bench_version) >= 2 && bench.fleet_mark != null;
    var threads = Number(hw.logical_cpus);
    var who = activePeerId() ? scopePeerLabel() : "this host";
    var html =
      "<p class=\"mb-1\">Hardware on " + esc(who) + ": <strong>" + esc(mark) + "</strong>" +
      (measured ? " <span class=\"text-body-secondary\">measured " + esc(measured) + "</span>" : "") +
      "</p>" +
      "<p class=\"mb-2\">In-process only: one single-core mix, one process per CPU, a memory copy, and a 256 MB file. No Docker, PostgreSQL, SQL, or NumPy.</p>";
    if (bench.fleet_mark == null) {
      html += "<p class=\"mb-2\">No hardware score yet.</p>";
    } else if (!scoresCurrent) {
      html += "<p class=\"mb-2\">Run hardware again to refresh the memory and disk parts of the score.</p>";
    }
    if (bench.fleet_mark != null) {
      html +=
        "<dl class=\"row mb-2\">" +
        "<dt class=\"col-4\">Single-core</dt><dd class=\"col-8\">Score " + esc(scoreCell(bench.cpu_single_mark)) + "</dd>" +
        "<dt class=\"col-4\">All cores</dt><dd class=\"col-8\">Score " + esc(scoreCell(bench.cpu_multi_mark)) + "</dd>" +
        "<dt class=\"col-4\">Memory</dt><dd class=\"col-8\">" +
        (scoresCurrent ? "Score " + esc(scoreCell(bench.memory_mark)) + " · " : "") +
        esc(fmtRate(timings.memory_mbps)) +
        "</dd>" +
        "<dt class=\"col-4\">Disk</dt><dd class=\"col-8\">" +
        (scoresCurrent ? "Score " + esc(scoreCell(bench.disk_mark)) + " · " : "") +
        "read " + esc(fmtRate(timings.disk_read_mbps)) +
        ", write " + esc(fmtRate(timings.disk_write_mbps)) +
        "</dd></dl>";
    }
    var fms = profile && profile.fmsbench && typeof profile.fmsbench === "object" ? profile.fmsbench : { status: "not_run" };
    var fmsStatus = fms.status || "not_run";
    html += "<p class=\"small fw-semibold mb-1\">Market Studio</p>";
    html += "<p class=\"mb-2\">Status: <strong>" + esc(fmsStatus) + "</strong>";
    if (fms.profile) html += " · profile " + esc(fms.profile);
    if (isFinite(threads) && threads > 0) html += " · stress width " + (threads * 2);
    if (fms.finished_at) {
      try {
        html += " · finished " + esc(new Date(fms.finished_at * 1000).toLocaleString());
      } catch (_e2) { /* keep the status line */ }
    }
    html += "</p>";
    if (fms.summary && typeof fms.summary === "object") {
      var sum = fms.summary;
      html +=
        "<dl class=\"row mb-2\">" +
        "<dt class=\"col-4\">PostgreSQL</dt><dd class=\"col-8\">" + esc(rateOrDash(sum.postgres_jobs_per_second)) + " bundles/s</dd>" +
        "<dt class=\"col-4\">DuckDB</dt><dd class=\"col-8\">" + esc(rateOrDash(sum.duckdb_jobs_per_second)) + " bundles/s</dd>" +
        "<dt class=\"col-4\">SQLite</dt><dd class=\"col-8\">" + esc(rateOrDash(sum.sqlite_jobs_per_second)) + " bundles/s</dd>" +
        "<dt class=\"col-4\">Compute</dt><dd class=\"col-8\">" + esc(rateOrDash(sum.compute_rows_per_second)) + " rows/s</dd>" +
        "<dt class=\"col-4\">NLP</dt><dd class=\"col-8\">" + esc(rateOrDash(sum.nlp_docs_per_second)) + " docs/s</dd>" +
        "</dl>";
    } else if (fmsStatus === "not_run") {
      html += "<p class=\"mb-2\">No Market Studio run yet. The hardware score stays as it is.</p>";
    } else if (fms.detail || fms.error) {
      html += "<p class=\"mb-2\">" + esc(fms.detail || fms.error) + "</p>";
    }
    if (fms.phases) {
      var phaseNames = [
        ["postgres_prepare", "PostgreSQL load"],
        ["postgres_sql", "PostgreSQL SQL"],
        ["duckdb_sql", "DuckDB SQL"],
        ["sqlite_sql", "SQLite SQL"],
        ["numpy_compute", "NumPy compute"],
        ["nlp_memory", "NLP 1 GiB"]
      ];
      html += "<ul class=\"mb-2\">";
      phaseNames.forEach(function (pair) {
        html += "<li>" + esc(pair[1]) + ": " + (fms.phases[pair[0]] ? "recorded" : "not recorded") + "</li>";
      });
      html += "</ul>";
    }
    if (fmsStatus === "running" || fms.stress_status === "running" || fms.width_status === "running" || fms.full_status === "running") {
      paintFms(fms, who);
    } else if (profile && profile.benchmark_progress && profile.benchmark_progress.status === "running") {
      paintFleet(profile.benchmark_progress, who, Number(profile.benchmark_progress.started_at) || Date.now() / 1000);
    }
    root.innerHTML = html;
  }

  function renderSecurity(blocks, events) {
    var root = document.getElementById("fleet-capacity-security-body");
    if (!root) return;
    var siege = blocks && blocks.siege_active;
    var rows = blocks && blocks.blocks ? blocks.blocks : [];
    var evs = events && events.events ? events.events : [];
    var html = "<p class=\"mb-1\">Siege mode: <strong>" + (siege ? "active" : "off") + "</strong></p>";
    html += "<p class=\"mb-1\">Active blocks: " + rows.length + "</p>";
    if (evs.length) {
      html += "<ul class=\"mb-0\">";
      evs.slice(0, 8).forEach(function (ev) {
        html +=
          "<li>" +
          esc(ev.severity) +
          " " +
          esc(ev.rule) +
          " " +
          esc(ev.source) +
          " " +
          esc(ev.path) +
          "</li>";
      });
      html += "</ul>";
    } else {
      html += "<p class=\"mb-0\">No recent security events.</p>";
    }
    root.innerHTML = html;
  }

  function refreshCapacity() {
    syncCapacityScope();
    var peer = activePeerId();
    if (peer) {
      var root = document.getElementById("fleet-capacity-mesh-body");
      if (root) root.textContent = "Loading " + scopePeerLabel() + "…";
      var base = "/v1/remote-peers/" + encodeURIComponent(peer);
      Promise.all([
        fleetApi(base + "/host/profile").then(function (r) {
          return r.json().then(function (j) {
            if (!r.ok) throw new Error((j && j.error) || "HTTP " + r.status);
            return j;
          });
        }),
        fleetApi(base + "/mesh/links")
          .then(function (r) {
            return r.json();
          })
          .catch(function () {
            return { edges: [] };
          }),
      ])
        .then(function (parts) {
          if (activePeerId() !== peer) return;
          renderMesh(parts[0], parts[1]);
          renderPeerBench(parts[0]);
          loadCompare();
        })
        .catch(function (e) {
          if (activePeerId() !== peer) return;
          if (root) root.textContent = "Could not load this peer: " + (e && e.message ? e.message : e);
        });
      return;
    }
    var diskBody = document.getElementById("fleet-capacity-disk-body");
    if (!diskBody) return;
    diskBody.textContent = "Loading…";
    var memBody = document.getElementById("fleet-capacity-memory-body");
    if (memBody) memBody.textContent = "Loading…";
    Promise.all([
      fleetApi("/v1/admin/space").then(function (r) {
        return r.json();
      }),
      fleetApi("/v1/admin/memory").then(function (r) {
        return r.json();
      }),
      fleetApi("/v1/admin/capacity/policy").then(function (r) {
        return r.json();
      }),
      fleetApi("/v1/host/profile").then(function (r) {
        return r.json();
      }),
      fleetApi("/v1/mesh/links").then(function (r) {
        return r.json();
      }),
      fleetApi("/v1/admin/security/blocks").then(function (r) {
        return r.json();
      }),
      fleetApi("/v1/admin/security/events?period_sec=3600").then(function (r) {
        return r.json();
      }),
    ])
      .then(function (parts) {
        renderDisk(parts[0]);
        renderMemory(parts[1], parts[2]);
        renderMesh(parts[3], parts[4]);
        renderPeerBench(parts[3]);
        renderSecurity(parts[5], parts[6]);
        loadCompare();
      })
      .catch(function (e) {
        setMsg("fleet-capacity-msg", String(e), true);
      });
  }

  function savePolicy() {
    if (isRemoteScope()) {
      setMsg("fleet-capacity-msg", "Read-only remote scope.", true);
      return;
    }
    var spaceEn = document.getElementById("fleet-cap-space-enabled");
    var memEn = document.getElementById("fleet-cap-memory-enabled");
    var apply = document.getElementById("fleet-cap-apply-stops");
    var floor = document.getElementById("fleet-cap-floor-gib");
    var coldH = document.getElementById("fleet-cap-cold-hours");
    var warmH = document.getElementById("fleet-cap-warm-hours");
    var patch = {
      space: { enabled: spaceEn ? spaceEn.checked : null },
      memory: {
        enabled: memEn ? memEn.checked : true,
        apply_stops: apply ? apply.checked : false,
        free_ram_floor_gib: floor ? parseFloat(floor.value) : 16,
        cold_idle_hours: coldH ? parseFloat(coldH.value) : 2,
        warm_idle_hours: warmH ? parseFloat(warmH.value) : 6,
      },
    };
    fleetApi("/v1/admin/capacity/policy", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    })
      .then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok) throw new Error(j.detail || j.error || r.statusText);
          return j;
        });
      })
      .then(function () {
        setMsg("fleet-capacity-msg", "Policy saved.");
        refreshCapacity();
      })
      .catch(function (e) {
        setMsg("fleet-capacity-msg", String(e), true);
      });
  }

  function runSpace(dry) {
    if (isRemoteScope()) {
      setMsg("fleet-capacity-msg", "Read-only remote scope.", true);
      return;
    }
    fleetApi("/v1/admin/space/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tier: 0, dry_run: !!dry }),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (j) {
        setMsg("fleet-capacity-msg", dry ? "Disk dry-run complete." : "Disk tier 0 run sent.");
        renderDisk({ ok: true, last_run: j, pressure: j.pressure, guardian_enabled: true });
        refreshCapacity();
      })
      .catch(function (e) {
        setMsg("fleet-capacity-msg", String(e), true);
      });
  }

  function runMemory(dry) {
    if (isRemoteScope()) {
      setMsg("fleet-capacity-msg", "Read-only remote scope.", true);
      return;
    }
    fleetApi("/v1/admin/memory/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tier: dry ? 0 : 1, dry_run: !!dry }),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (j) {
        setMsg(
          "fleet-capacity-msg",
          j.skipped && j.reason === "apply_stops_disabled"
            ? "Memory apply_stops is off — plan only."
            : dry
              ? "Memory dry-run complete."
              : "Memory run complete."
        );
        refreshCapacity();
      })
      .catch(function (e) {
        setMsg("fleet-capacity-msg", String(e), true);
      });
  }

  var compareTimer = null;

  function comparisonBusy(doc) {
    if (doc && doc.batch && doc.batch.status === "running") return true;
    var rows = doc && doc.rows ? doc.rows : [];
    return rows.some(function (row) {
      var fms = row.fmsbench || {};
      return fms.status === "running" || fms.stress_status === "running" || fms.width_status === "running" || fms.full_status === "running";
    });
  }

  function loadCompare() {
    var root = document.getElementById("fleet-capacity-compare-body");
    var measure = document.getElementById("fleet-bench-measure-body");
    if (!root && !measure) return;
    Promise.all([
      fleetApi("/v1/mesh/benchmarks").then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok) throw new Error((j && j.error) || "HTTP " + r.status);
          return j;
        });
      }),
      fleetApi("/v1/mesh/capacity").then(function (r) {
        return r.json().then(function (j) {
          return r.ok && j ? j : { nodes: [] };
        });
      }).catch(function () {
        return { nodes: [] };
      }),
      fleetApi("/v1/remote-peers").then(function (r) {
        return r.json().then(function (j) {
          return r.ok && j ? j : { peers: [] };
        });
      }).catch(function () {
        return { peers: [] };
      }),
    ])
      .then(function (parts) {
        renderScoreboard(parts[0], parts[1]);
        if (window.forgeFleetBenchmarksView && typeof window.forgeFleetBenchmarksView.render === "function") {
          window.forgeFleetBenchmarksView.render(parts[0], { peers: (parts[2] && parts[2].peers) || [] });
        }
        if (comparisonBusy(parts[0]) && !compareTimer) {
          compareTimer = setTimeout(function () {
            compareTimer = null;
            loadCompare();
            refreshCapacity();
          }, 5000);
        }
      })
      .catch(function (e) {
        var message = "Could not load scores: " + (e && e.message ? e.message : e);
        if (root) root.textContent = message;
        if (measure) measure.textContent = message;
      });
  }

  function peerLabel(row) {
    var who = row.label || row.peer_id || "peer";
    if (row.node_id && row.node_id !== who) who += " (" + row.node_id + ")";
    if (row.from_saved) who += " · saved";
    return who;
  }

  function headroomFor(row, mesh) {
    var nodes = mesh && mesh.nodes ? mesh.nodes : [];
    var id = row && row.peer_id;
    var found = null;
    nodes.forEach(function (node) {
      if (found) return;
      if (id === "local" && node.scope === "local") found = node;
      else if (node.peer_id && node.peer_id === id) found = node;
    });
    return found && found.capacity ? found.capacity : null;
  }

  function fmtMb(mb) {
    var n = Number(mb);
    if (!isFinite(n) || n < 0) return "—";
    if (n >= 1024) return (n / 1024).toFixed(1) + " GiB";
    return Math.round(n) + " MiB";
  }

  function fmtSeconds(n) {
    if (!hasNumeric(n)) return "—";
    return Number(n).toFixed(1) + "s";
  }

  function renderScoreboard(doc, mesh) {
    var root = document.getElementById("fleet-capacity-compare-body");
    if (!root) return;
    var rows = doc && doc.rows ? doc.rows : [];
    if (!rows.length) {
      root.textContent = "No peers to show.";
      return;
    }
    var cluster = doc && doc.cluster_score != null ? doc.cluster_score : "—";
    var html = "<p class=\"h4 mb-1\">Cluster <strong>" + esc(cluster) + "</strong></p>" +
      "<p class=\"small text-body-secondary mb-2\">Sum of complete composites. Each point is this server's capacity. A partial row drops out once this server has an NLP result.</p>" +
      "<table class=\"table table-sm mb-0\"><thead><tr>" +
      "<th>Peer</th><th>Composite</th><th>Hardware</th><th>Cores</th><th>Threads</th><th>CPU free</th><th>RAM free</th>" +
      "</tr></thead><tbody>";
    rows.forEach(function (row) {
      var fleet = row.fleet || {};
      var fms = row.fmsbench || {};
      var cap = row.capacity || {};
      var live = headroomFor(row, mesh) || {};
      var cpu = live.cpu || {};
      var mem = live.memory || {};
      var composite = scoreCell(fms.composite_score);
      if (fms.composite_nlp === false && doc.reference_nlp) composite += " partial";
      else if (composite === "—" && fms.status) composite = fms.status;
      var cpuFree = cpu.available_cores != null ? cpu.available_cores + (cpu.cores_logical ? " / " + cpu.cores_logical : "") : "—";
      html += "<tr><td>" + esc(peerLabel(row)) + "</td><td>" + esc(composite) + "</td><td>" +
        esc(scoreCell(fleet.fleet_mark)) + "</td><td>" +
        esc(cap.physical_cores != null ? cap.physical_cores : (cpu.cores_physical != null ? cpu.cores_physical : "—")) + "</td><td>" +
        esc(cap.hardware_threads != null ? cap.hardware_threads : (cpu.cores_logical != null ? cpu.cores_logical : "—")) + "</td><td>" +
        esc(cpuFree) + "</td><td>" + esc(fmtMb(mem.available_mb)) + "</td></tr>";
    });
    html += "</tbody></table>";
    root.innerHTML = html;
  }

  var FLEET_STEPS = [
    ["cpu_single", "Single-core mix"],
    ["cpu_multi", "All cores"],
    ["memory", "Memory copy"],
    ["disk", "256 MB disk file"],
    ["save", "Save hardware score"]
  ];
  var FMS_STEPS = [
    ["check", "Check the host"],
    ["image", "Pull or build images"],
    ["postgres_up", "Start PostgreSQL"],
    ["load", "Load fixture data"],
    ["postgres_sql", "PostgreSQL SQL"],
    ["duckdb_sql", "DuckDB SQL"],
    ["sqlite_sql", "SQLite SQL"],
    ["numpy", "NumPy compute"],
    ["nlp", "NLP 1 GiB"],
    ["save", "Save the result"]
  ];

  function fmtElapsed(sec) {
    var s = Math.max(0, Math.round(Number(sec) || 0));
    var m = Math.floor(s / 60);
    return m + ":" + (s % 60 < 10 ? "0" : "") + (s % 60);
  }

  function stepStates(catalog, activeId, status) {
    var idx = 0;
    catalog.forEach(function (pair, i) {
      if (pair[0] === activeId) idx = i;
    });
    if (status === "passed" || status === "finished") idx = catalog.length;
    return catalog.map(function (pair, i) {
      var state = "pending";
      if (status === "failed" || status === "incomplete" || status === "stale") {
        if (i < idx) state = "done";
        else if (i === idx) state = "failed";
      } else if (i < idx) state = "done";
      else if (i === idx) state = "active";
      return { label: pair[1], state: state };
    });
  }

  function fmsStepId(phase) {
    var p = String(phase || "").toLowerCase();
    if (p.indexOf("stopping") >= 0 || p.indexOf("saving") >= 0) return "save";
    if (p.indexOf("nlp") >= 0) return "nlp";
    if (p.indexOf("numpy") >= 0) return "numpy";
    if (p.indexOf("sqlite sql") >= 0) return "sqlite_sql";
    if (p.indexOf("duckdb") >= 0) return "duckdb_sql";
    if (p.indexOf("postgresql sql") >= 0 || p.indexOf("upsert") >= 0) return "postgres_sql";
    if (p.indexOf("loading") >= 0) return "load";
    if (p.indexOf("starting postgresql") >= 0) return "postgres_up";
    if (p.indexOf("pulling") >= 0 || p.indexOf("building") >= 0) return "image";
    return "check";
  }

  function renderLive(model) {
    var root = document.getElementById("fleet-cap-live");
    if (!root || !model) return;
    var active = (model.steps || []).filter(function (step) { return step.state === "active"; })[0];
    var html = "<div class=\"border rounded p-2 mb-2\">";
    html += "<p class=\"mb-1\"><strong>" + esc(model.title) + "</strong> · " + esc(fmtElapsed(model.elapsed)) + "</p>";
    if (active) html += "<p class=\"mb-1 fw-semibold\">Now: " + esc(active.label) + "</p>";
    if (model.note) html += "<p class=\"text-body-secondary mb-2\">" + esc(model.note) + "</p>";
    html += "<ol class=\"mb-2\">";
    (model.steps || []).forEach(function (step) {
      var mark = step.state === "done" ? "Done" : step.state === "active" ? "Now" : step.state === "failed" ? "Stopped" : "Waiting";
      var cls = step.state === "active" ? "fw-semibold" : step.state === "failed" ? "text-danger" : "text-body-secondary";
      html += "<li class=\"" + cls + "\">" + esc(mark) + " — " + esc(step.label) + "</li>";
    });
    html += "</ol>";
    if (model.detail) html += "<p class=\"mb-2\">" + esc(model.detail) + "</p>";
    if (model.log) {
      html += "<p class=\"small mb-1 text-body-secondary\">Latest log</p>";
      html += "<pre class=\"small mb-0\" style=\"max-height:12rem;overflow:auto;white-space:pre-wrap\">" + esc(model.log) + "</pre>";
    }
    html += "</div>";
    root.innerHTML = html;
    var pane = document.getElementById("fleet-tab-benchmarks");
    if (root.scrollIntoView && pane && pane.classList.contains("active")) {
      root.scrollIntoView({ block: "nearest" });
    }
  }

  function tailLog(text) {
    var lines = String(text || "").split("\n").filter(function (line) { return line.trim(); });
    return lines.slice(-6).join("\n");
  }

  function paintFleet(progress, who, clickStarted) {
    var started = Number(progress && progress.started_at) || clickStarted;
    var status = progress && progress.status === "failed" ? "failed" : "running";
    renderLive({
      title: "Hardware on " + who,
      note: "In-process CPU, memory, and disk. No Docker or PostgreSQL.",
      elapsed: Date.now() / 1000 - started,
      steps: stepStates(FLEET_STEPS, progress && progress.step, status),
      detail: progress && progress.detail ? progress.detail : ""
    });
  }

  function fmsStressLive(fms) {
    return !!(fms && fms.stress_status === "running");
  }

  function fmsSideLive(fms) {
    return !!(fms && (fms.stress_status === "running" || fms.width_status === "running" || fms.full_status === "running"));
  }

  function paintFms(fms, who) {
    var side = fmsSideLive(fms);
    var started = Number(side && fms.stress_status === "running" ? fms.stress_started_at : fms && fms.started_at) || Date.now() / 1000;
    var status = side ? "running" : (fms && fms.status ? fms.status : "running");
    var finished = status === "passed" ? "passed" : status === "running" ? "running" : status;
    var title = "Market Studio on " + who;
    if (fms && fms.stress_status === "running") title = "Market Studio stress on " + who;
    if (fms && fms.width_status === "running") title = (fms.width_profile || "Host max") + " on " + who;
    if (fms && fms.full_status === "running") title = "Full Market Studio on " + who;
    renderLive({
      title: title,
      note: side
        ? "The saved standard result stays in place until a standard or full run replaces it."
        : "Forge Benchmarks Market Studio. Containers, PostgreSQL, DuckDB, SQLite, and NumPy. Work files are removed after the result is saved.",
      elapsed: Date.now() / 1000 - started,
      steps: stepStates(FMS_STEPS, fmsStepId(fms && fms.phase), finished),
      detail: fms && fms.phase ? fms.phase : "Waiting for the first log line.",
      log: tailLog(fms && fms.log_excerpt)
    });
  }

  function fmsOutcomeText(fms, who, mode) {
    if (fmsStressLive(fms) || mode === "stress") {
      if (fms && fms.stress_status === "passed" && fms.stress && fms.stress.threads) {
        return "Stress test passed on " + who + " at " + fms.stress.threads + " threads. The standard result is unchanged.";
      }
      if (fms && fms.stress_status === "failed") {
        return "Stress test failed on " + who + ". " + (fms.stress_error || "The standard result is unchanged.");
      }
      var phase = fms && fms.phase ? " Current step: " + fms.phase + "." : "";
      var stressLog = lastLogLine(fms);
      return "Stress test is still running on " + who + "." + phase + (stressLog ? " Last log: " + stressLog : "");
    }
    if (mode === "width" || (fms && fms.width_status === "running")) {
      if (fms && fms.width_status === "passed") {
        return (fms.width_profile || "Host max") + " passed on " + who + ". The standard result is unchanged.";
      }
      if (fms && fms.width_status === "failed") {
        return (fms.width_profile || "Host max") + " failed on " + who + ". " + (fms.width_error || "The standard result is unchanged.");
      }
      var widthLog = lastLogLine(fms);
      return (fms && fms.width_profile ? fms.width_profile : "Host max") + " is still running on " + who + "." + (fms && fms.phase ? " " + fms.phase + "." : "") + (widthLog ? " Last log: " + widthLog : "");
    }
    if (mode === "full" || (fms && fms.full_status === "running")) {
      if (fms && fms.full_status === "passed") return "Full test passed on " + who + ". Standard, host max, and stress are saved.";
      if (fms && fms.full_status === "failed") return "Full test failed on " + who + ". " + (fms.full_error || "");
      var logLine = lastLogLine(fms);
      return "Full test is still running on " + who + ". " + (fms && fms.phase ? fms.phase + "." : "Waiting for the first log line.") + (logLine ? " Last log: " + logLine : "");
    }
    var status = fms && fms.status ? fms.status : "not_run";
    var phases = fms && fms.phases ? fms.phases : {};
    var bits = [];
    if (phases.postgres_sql) bits.push("PostgreSQL SQL");
    if (phases.duckdb_sql) bits.push("DuckDB SQL");
    if (phases.sqlite_sql) bits.push("SQLite SQL");
    if (phases.numpy_compute) bits.push("NumPy");
    if (phases.nlp_memory) bits.push("NLP");
    var evidence = bits.length ? " Evidence: " + bits.join(", ") + "." : " No engine evidence was recorded.";
    if (status === "passed") return "Market Studio passed on " + who + "." + evidence;
    if (status === "running") {
      var runningPhase = fms && fms.phase ? " Current step: " + fms.phase + "." : " Waiting for the first log line.";
      var runningLog = lastLogLine(fms);
      return "Market Studio is still running on " + who + "." + runningPhase + (runningLog ? " Last log: " + runningLog : "");
    }
    var why = fms && (fms.detail || fms.error) ? " " + (fms.detail || fms.error) : "";
    return "Market Studio " + status + " on " + who + "." + evidence + why;
  }

  function watchFms(peer, who, fmsBtn, mode) {
    var tries = 0;
    var inflight = false;
    var latest = { status: "running", phase: "Checking the host", started_at: Date.now() / 1000 };
    paintFms(latest, who);
    var timer = setInterval(function () {
      tries += 1;
      paintFms(latest, who);
      setFmsStatus(fmsOutcomeText(latest, who, mode) + fmsElapsedText(latest));
      if (inflight) return;
      inflight = true;
      var path = peer
        ? "/v1/remote-peers/" + encodeURIComponent(peer) + "/host/profile"
        : "/v1/host/profile";
      fleetApi(path)
        .then(function (r) { return r.json(); })
        .then(function (j) {
          var fms = j && j.fmsbench ? j.fmsbench : { status: "not_run" };
          latest = fms;
          paintFms(latest, who);
          var still = mode === "stress" ? fmsStressLive(fms) : mode === "width" ? fms.width_status === "running" : mode === "full" ? fms.full_status === "running" || fms.status === "running" : fms.status === "running";
          var notYet = !fms || fms.status === "not_run" || (mode === "stress" && !fms.stress_status) || (mode === "width" && !fms.width_status) || (mode === "full" && fms.full_status !== "running" && fms.status !== "running" && fms.full_status !== "passed" && fms.full_status !== "failed");
          if ((still || (notYet && tries < 20)) && tries < 16000) {
            setFmsStatus(fmsOutcomeText(fms, who, mode) + fmsElapsedText(fms));
            return;
          }
          clearInterval(timer);
          var failed = mode === "stress" ? fms.stress_status !== "passed" : mode === "width" ? fms.width_status !== "passed" : mode === "full" ? fms.full_status !== "passed" : fms.status !== "passed";
          setFmsStatus(fmsOutcomeText(fms, who, mode), failed);
          if (fmsBtn) {
            fmsBtn.disabled = false;
            fmsBtn.textContent = "This peer · Market Studio";
          }
          refreshCapacity();
        })
        .catch(function (err) {
          if (tries < 16000) {
            setFmsStatus("The run was accepted, but reading progress from " + who + " failed. Retrying. " + (err && err.message ? err.message : ""), true);
            return;
          }
          clearInterval(timer);
          if (fmsBtn) {
            fmsBtn.disabled = false;
            fmsBtn.textContent = "This peer · Market Studio";
          }
        })
        .finally(function () {
          inflight = false;
        });
    }, 1000);
  }

  function explainFmsError(message, who) {
    if (message === "not_found") {
      return who + " does not expose Forge Benchmarks. That peer is still on an older Fleet build. Upgrade it, then launch again.";
    }
    if (message === "compose_unavailable") {
      return who + " has no Docker Compose, so the Market Studio run cannot start.";
    }
    if (message === "unknown_profile") {
      return who + " does not recognize this profile. Upgrade that peer, then launch again.";
    }
    return message || "The run did not start.";
  }

  function fmsElapsedText(fms) {
    var started = Number(fms && (fms.started_at || fms.stress_started_at)) || 0;
    if (!started) return "";
    return " Elapsed " + fmtElapsed(Date.now() / 1000 - started) + ".";
  }

  function lastLogLine(fms) {
    var lines = String(fms && fms.log_excerpt || "").split("\n").filter(function (line) { return line.trim(); });
    return lines.length ? lines[lines.length - 1] : "";
  }

  function setFmsStatus(text, isErr) {
    var el = document.getElementById("fleet-cap-fms-status");
    if (!el) return;
    el.textContent = text || "";
    el.className = "small mb-0 mt-1 " + (isErr ? "text-danger" : "text-body-secondary");
  }

  function openBenchmarksTab() {
    var btn = document.getElementById("fleet-tab-benchmarks-btn");
    if (btn && window.bootstrap && window.bootstrap.Tab) {
      window.bootstrap.Tab.getOrCreateInstance(btn).show();
    }
  }

  function wireCapacityUi() {
    if (window.location.hash === "#benchmarks") {
      openBenchmarksTab();
    }
    window.addEventListener("hashchange", function () {
      if (window.location.hash === "#benchmarks") openBenchmarksTab();
    });
    var tabBtn = document.getElementById("fleet-tab-capacity-btn");
    if (tabBtn) {
      tabBtn.addEventListener("shown.bs.tab", function () {
        refreshCapacity();
      });
    }
    var benchTab = document.getElementById("fleet-tab-benchmarks-btn");
    if (benchTab) {
      benchTab.addEventListener("shown.bs.tab", function () {
        refreshCapacity();
      });
    }
    var openBench = document.getElementById("fleet-open-benchmarks-btn");
    if (openBench) {
      openBench.addEventListener("click", function () {
        if (window.location.hash !== "#benchmarks") {
          window.location.hash = "benchmarks";
        }
        openBenchmarksTab();
      });
    }
    var ref = document.getElementById("fleet-capacity-refresh-btn");
    if (ref) ref.addEventListener("click", refreshCapacity);
    var benchBtn = document.getElementById("fleet-cap-bench-btn");
    if (benchBtn) {
      benchBtn.addEventListener("click", function () {
        if (benchBtn.disabled) return;
        var peer = activePeerId();
        var benchPath = peer
          ? "/v1/remote-peers/" + encodeURIComponent(peer) + "/host/profile/benchmark"
          : "/v1/host/profile/benchmark";
        var who = peer ? scopePeerLabel() : "this host";
        var profilePath = peer
          ? "/v1/remote-peers/" + encodeURIComponent(peer) + "/host/profile"
          : "/v1/host/profile";
        var clickStarted = Date.now() / 1000;
        var latest = {
          step: "cpu_single",
          status: "running",
          detail: "Single-core mix",
          started_at: clickStarted
        };
        var inflight = false;
        benchBtn.disabled = true;
        benchBtn.textContent = "Running hardware…";
        paintFleet(latest, who, clickStarted);
        setBenchStatus("Hardware running on " + who + ". Watch the steps above. This does not start containers.");
        setMsg("fleet-bench-msg", "Hardware running on " + who + ".");
        var liveTimer = setInterval(function () {
          paintFleet(latest, who, clickStarted);
          setBenchStatus("Hardware on " + who + " · " + (latest.detail || latest.step || "starting") + " · elapsed " + fmtElapsed(Date.now() / 1000 - clickStarted) + ".");
          if (inflight) return;
          inflight = true;
          fleetApi(profilePath)
            .then(function (r) { return r.json(); })
            .then(function (j) {
              if (j && j.benchmark_progress && j.benchmark_progress.kind === "fleet_mark") {
                latest = j.benchmark_progress;
              }
            })
            .catch(function () {})
            .finally(function () { inflight = false; });
        }, 1000);
        fleetApi(benchPath, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        })
          .then(function (r) {
            return r.json().then(function (j) {
              if (!r.ok) throw new Error(benchErrorText(j, r.statusText));
              return j;
            });
          })
          .then(function (j) {
            if (liveTimer) clearInterval(liveTimer);
            liveTimer = null;
            var mark = j && j.benchmark && j.benchmark.fleet_mark != null ? j.benchmark.fleet_mark : null;
            var done = mark != null
              ? "Hardware score " + mark + " saved. In-process CPU, memory, and disk only. Docker and PostgreSQL were not started."
              : "Hardware finished. Docker and PostgreSQL were not started.";
            renderLive({
              title: "Hardware on " + who,
              note: "In-process CPU, memory, and disk. No Docker or PostgreSQL.",
              elapsed: Date.now() / 1000 - clickStarted,
              steps: stepStates(FLEET_STEPS, "save", "finished"),
              detail: done
            });
            setMsg("fleet-bench-msg", done);
            setBenchStatus(done);
            refreshCapacity();
          })
          .catch(function (e) {
            if (liveTimer) clearInterval(liveTimer);
            liveTimer = null;
            var msg = e && e.message ? e.message : String(e);
            if (msg === "Failed to fetch") {
              msg = "The benchmark request did not return. Fleet may still be busy with it.";
            }
            renderLive({
              title: "Hardware on " + who,
              note: "In-process CPU, memory, and disk. No Docker or PostgreSQL.",
              elapsed: Date.now() / 1000 - clickStarted,
              steps: stepStates(FLEET_STEPS, latest.step || "cpu_single", "failed"),
              detail: msg
            });
            setMsg("fleet-bench-msg", msg, true);
            setBenchStatus(msg, true);
          })
          .finally(function () {
            benchBtn.disabled = false;
            benchBtn.textContent = "This peer · hardware";
          });
      });
    }
    var fmsBtn = document.getElementById("fleet-cap-fms-btn");
    if (fmsBtn) {
      fmsBtn.addEventListener("click", function () {
        if (fmsBtn.disabled) return;
        var peer = activePeerId();
        var path = peer
          ? "/v1/remote-peers/" + encodeURIComponent(peer) + "/host/profile/fmsbench"
          : "/v1/host/profile/fmsbench";
        var sel = document.getElementById("fleet-cap-fms-profile");
        var profile = sel && sel.value ? sel.value : "smoke";
        var who = peer ? scopePeerLabel() : "this host";
        fmsBtn.disabled = true;
        fmsBtn.textContent = "Starting Market Studio…";
        paintFms({ status: "running", phase: "Sending the start request", started_at: Date.now() / 1000, profile: profile }, who);
        setFmsStatus("Sending " + profile + " to " + who + ". The checklist stays on this step until the peer accepts the run.");
        fleetApi(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile: profile }),
        })
          .then(function (r) {
            return r.json().then(function (j) {
              if (!r.ok) throw new Error((j && (j.detail || j.error)) || r.statusText);
              return j;
            });
          })
          .then(function (j) {
            var startedDoc = j && j.fmsbench ? j.fmsbench : {};
            var status = startedDoc.status || (j && j.status) || "running";
            var mode = profile === "stress" ? "stress" : profile === "full" ? "full" : profile.indexOf("host-max") === 0 ? "width" : "standard";
            if (status === "running" || startedDoc.stress_status === "running" || startedDoc.width_status === "running" || startedDoc.full_status === "running" || (j && j.status === "running")) {
              fmsBtn.textContent = mode === "stress" ? "Stress test running…" : "Market Studio running…";
              setFmsStatus(mode === "stress"
                ? "Stress test is running on " + who + " at twice the hardware threads. The standard result stays in place."
                : "Market Studio is still running on " + who + ". The checklist above updates as each engine starts.");
              watchFms(peer, who, fmsBtn, mode);
              return;
            }
            paintFms(j && j.fmsbench ? j.fmsbench : { status: status, phase: "Checking the host" }, who);
            setFmsStatus(fmsOutcomeText(j && j.fmsbench, who), status !== "passed");
            fmsBtn.disabled = false;
            fmsBtn.textContent = "This peer · Market Studio";
            refreshCapacity();
          })
          .catch(function (e) {
            var message = explainFmsError(e && e.message ? e.message : String(e), who);
            renderLive({
              title: profile + " on " + who,
              note: "The run did not start. The hardware score is unchanged.",
              elapsed: 0,
              steps: stepStates(FMS_STEPS, "check", "failed"),
              detail: message
            });
            setFmsStatus(message, true);
            fmsBtn.disabled = false;
            fmsBtn.textContent = "This peer · Market Studio";
          });
      });
    }
    function runAll(suite, button, idleLabel) {
      if (!button || button.disabled) return;
      button.disabled = true;
      button.textContent = "Starting…";
      fleetApi("/v1/mesh/benchmarks/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ suite: suite, profile: "standard" }),
      })
        .then(function (r) {
          return r.json().then(function (j) {
            if (!r.ok) throw new Error((j && (j.detail || j.error)) || r.statusText);
            return j;
          });
        })
        .then(function (j) {
          var targets = j && j.targets ? j.targets : [];
          var names = targets.map(function (target) { return target.label || target.peer_id; });
          setMsg("fleet-bench-msg", "Started " + (suite === "hardware" ? "hardware" : "Market Studio") + " on " + names.join(", ") + ".");
          loadCompare();
        })
        .catch(function (e) {
          setMsg("fleet-bench-msg", e && e.message ? e.message : String(e), true);
        })
        .finally(function () {
          button.disabled = false;
          button.textContent = idleLabel;
        });
    }
    var benchAll = document.getElementById("fleet-cap-bench-all-btn");
    if (benchAll) {
      benchAll.addEventListener("click", function () {
        runAll("hardware", benchAll, "Re-run all hardware");
      });
    }
    var fmsAll = document.getElementById("fleet-cap-fms-all-btn");
    if (fmsAll) {
      fmsAll.addEventListener("click", function () {
        runAll("market_studio", fmsAll, "Re-run all Market Studio");
      });
    }
    var diskDry = document.getElementById("fleet-cap-disk-dry-btn");
    if (diskDry) diskDry.addEventListener("click", function () {
      runSpace(true);
    });
    var memDry = document.getElementById("fleet-cap-memory-dry-btn");
    if (memDry) memDry.addEventListener("click", function () {
      runMemory(true);
    });
    var memApply = document.getElementById("fleet-cap-memory-apply-btn");
    if (memApply) memApply.addEventListener("click", function () {
      runMemory(false);
    });
    var save = document.getElementById("fleet-cap-policy-save-btn");
    if (save) save.addEventListener("click", savePolicy);
    var tier2 = document.getElementById("fleet-cap-memory-tier2-btn");
    if (tier2) {
      tier2.addEventListener("click", function () {
        if (isRemoteScope()) {
          setMsg("fleet-capacity-msg", "Read-only remote scope.", true);
          return;
        }
        var sidEl = document.getElementById("fleet-cap-tier2-sid");
        var confEl = document.getElementById("fleet-cap-tier2-confirm");
        var sid = sidEl ? String(sidEl.value || "").trim() : "";
        var conf = confEl ? String(confEl.value || "").trim() : "";
        if (!sid) {
          setMsg("fleet-capacity-msg", "Service id required.", true);
          return;
        }
        if (conf !== "STOP") {
          setMsg("fleet-capacity-msg", 'Type STOP in the confirm field.', true);
          return;
        }
        fleetApi("/v1/admin/memory/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tier: 2, dry_run: false, service_id: sid }),
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (j) {
            if (!j.ok) throw new Error(j.error || "tier2_failed");
            setMsg("fleet-capacity-msg", "Tier 2 stop sent for " + sid);
            refreshCapacity();
          })
          .catch(function (e) {
            setMsg("fleet-capacity-msg", String(e), true);
          });
      });
    }
    syncCapacityScope();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireCapacityUi);
  } else {
    wireCapacityUi();
  }

  window.fleetCapacityRefresh = refreshCapacity;
})();
