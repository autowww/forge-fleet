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
    var title = document.getElementById("fleet-cap-profile-title");
    if (title) {
      title.textContent = remote ? "Host profile — " + scopePeerLabel() : "Host profile & mesh links";
    }
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

  function scoreCell(n) {
    var v = Number(n);
    return isFinite(v) ? String(Math.round(v)) : "—";
  }

  function renderMesh(profile, links) {
    var root = document.getElementById("fleet-capacity-mesh-body");
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
    var threads = Number(hw.logical_cpus);
    var cores = Number(hw.physical_cpus);
    var cpuLine = "—";
    if (isFinite(cores) && cores > 0 && isFinite(threads) && threads > cores) {
      cpuLine = cores + " cores, " + threads + " threads";
    } else if (isFinite(threads) && threads > 0) {
      cpuLine = threads + (threads === 1 ? " core" : " cores");
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
    var scoresCurrent = Number(bench.bench_version) >= 2 && bench.fleet_mark != null;
    var html =
      "<p class=\"mb-1\">Fleet mark: <strong>" +
      esc(mark) +
      "</strong>" +
      (measured ? " <span class=\"text-body-secondary\">measured " + esc(measured) + "</span>" : "") +
      "</p>" +
      "<p class=\"mb-2\">One score from single-core speed, all-core speed, memory speed, and disk speed. Higher is faster.</p>" +
      "<p class=\"small fw-semibold mb-1\">" +
      esc(activePeerId() ? "On " + scopePeerLabel() : "On this host") +
      "</p>" +
      "<dl class=\"row mb-2\">" +
      "<dt class=\"col-4\">CPU</dt><dd class=\"col-8\">" + esc(cpuLine) + "</dd>" +
      "<dt class=\"col-4\">Memory</dt><dd class=\"col-8\">" + esc(memLine) + "</dd>" +
      "<dt class=\"col-4\">Disk</dt><dd class=\"col-8\">" + esc(diskLine) + "</dd>" +
      "</dl>";
    if (bench.fleet_mark == null) {
      html += "<p class=\"mb-2\">No benchmark yet. Run one to score this host.</p>";
    } else if (!scoresCurrent) {
      html += "<p class=\"mb-2\">Run benchmark again to update the Fleet mark and the memory and disk scores.</p>";
    }
    if (bench.fleet_mark != null) {
      html +=
        "<p class=\"small fw-semibold mb-1\">What was measured</p>" +
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
        renderSecurity(parts[5], parts[6]);
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

  function wireCapacityUi() {
    var tabBtn = document.getElementById("fleet-tab-capacity-btn");
    if (tabBtn) {
      tabBtn.addEventListener("shown.bs.tab", function () {
        refreshCapacity();
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
        benchBtn.disabled = true;
        benchBtn.textContent = "Running benchmark…";
        setBenchStatus("Running on " + who + ". This usually takes under a minute. The Fleet mark updates here when it finishes.");
        setMsg("fleet-capacity-msg", "Benchmark running on " + who + ".");
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
            var mark = j && j.benchmark && j.benchmark.fleet_mark != null ? j.benchmark.fleet_mark : null;
            var done = mark != null ? "Benchmark complete. Fleet mark " + mark + "." : "Benchmark complete.";
            setMsg("fleet-capacity-msg", done);
            setBenchStatus(done);
            refreshCapacity();
          })
          .catch(function (e) {
            var msg = e && e.message ? e.message : String(e);
            if (msg === "Failed to fetch") {
              msg = "The benchmark request did not return. Fleet may still be busy with it.";
            }
            setMsg("fleet-capacity-msg", msg, true);
            setBenchStatus(msg, true);
          })
          .finally(function () {
            benchBtn.disabled = false;
            benchBtn.textContent = "Run benchmark";
          });
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
