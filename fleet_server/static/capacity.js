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
    return document.body.classList.contains("fleet-scope-remote");
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

  function refreshCapacity() {
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
    ])
      .then(function (parts) {
        renderDisk(parts[0]);
        renderMemory(parts[1], parts[2]);
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
    document.querySelectorAll(".fleet-capacity-local-only").forEach(function (el) {
      if (isRemoteScope()) el.classList.add("d-none");
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireCapacityUi);
  } else {
    wireCapacityUi();
  }

  window.fleetCapacityRefresh = refreshCapacity;
})();
