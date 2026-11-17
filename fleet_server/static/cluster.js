/* Fleet admin — Cluster tab (mesh nodes, containers, managed services). */
(function () {
  "use strict";

  var LS = "forgeFleetAdminToken";
  var POLL_MS = 10000;
  var pollTimer = null;
  var clusterTabActive = false;

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

  function fmtPct(v) {
    var n = Number(v);
    if (!isFinite(n)) return "—";
    return Math.round(n * 10) / 10 + "%";
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

  function nodeCap(node) {
    return node && node.capacity && typeof node.capacity === "object" ? node.capacity : {};
  }

  function maxGpuUtil(cap) {
    var gpu = cap.gpu;
    if (!Array.isArray(gpu) || !gpu.length) return null;
    var m = null;
    gpu.forEach(function (d) {
      var u = d && d.utilization_pct;
      if (u != null && !isNaN(Number(u))) m = m == null ? Number(u) : Math.max(m, Number(u));
    });
    return m;
  }

  function sumVramUsed(cap) {
    var gpu = cap.gpu;
    if (!Array.isArray(gpu)) return null;
    var sum = 0;
    var any = false;
    gpu.forEach(function (d) {
      if (d && d.vram_used_mb != null && !isNaN(Number(d.vram_used_mb))) {
        sum += Number(d.vram_used_mb);
        any = true;
      }
    });
    return any ? sum : null;
  }

  function serviceContainerMap(node) {
    var map = {};
    (node.services || []).forEach(function (svc) {
      var sid = String(svc.id || "");
      var st = svc.status;
      if (!st || !Array.isArray(st.services)) return;
      st.services.forEach(function (row) {
        var name = String((row && row.name) || "").trim();
        if (name && sid) map[name] = sid;
      });
    });
    return map;
  }

  function knownServiceIds(node) {
    var ids = {};
    (node.services || []).forEach(function (svc) {
      var sid = String(svc.id || "").trim();
      if (sid) ids[sid] = true;
    });
    return ids;
  }

  function renderMeshStrip(nodes) {
    var html = "";
    (nodes || []).forEach(function (node) {
      var cap = nodeCap(node);
      var cpu = cap.cpu || {};
      var mem = cap.memory || {};
      var stats = node.container_stats || {};
      var cnt = Array.isArray(stats.containers) ? stats.containers.length : 0;
      var svcN = Array.isArray(node.services) ? node.services.length : 0;
      var badge = node.ok
        ? '<span class="badge text-bg-success">ok</span>'
        : '<span class="badge text-bg-danger" title="' + esc((node.errors || []).join("; ")) + '">degraded</span>';
      html +=
        '<div class="col-sm-6 col-lg-4 col-xl-3">' +
        '<div class="border border-secondary-subtle rounded p-2 h-100 small">' +
        '<div class="fw-semibold mb-1 d-flex justify-content-between gap-2">' +
        '<span>' +
        esc(node.label || node.node_id || "node") +
        "</span> " +
        badge +
        "</div>" +
        '<div class="text-body-secondary fleet-mono">' +
        esc(node.role || "—") +
        " · CPU " +
        esc(fmtPct(cpu.used_pct)) +
        " · RAM " +
        esc(fmtPct(mem.used_pct)) +
        "<br>GPU " +
        esc(fmtPct(maxGpuUtil(cap))) +
        (sumVramUsed(cap) != null ? " · VRAM " + esc(String(sumVramUsed(cap)) + " MiB") : "") +
        "<br>" +
        esc(String(cnt)) +
        " containers · " +
        esc(String(svcN)) +
        " services" +
        "</div></div></div>";
    });
    return html || '<div class="col-12 text-body-secondary">No nodes.</div>';
  }

  function renderTotals(nodes) {
    var cores = 0;
    var ramMb = 0;
    var gpuN = 0;
    var containers = 0;
    var okNodes = 0;
    (nodes || []).forEach(function (node) {
      if (!node.ok) return;
      okNodes += 1;
      var cap = nodeCap(node);
      var cpu = cap.cpu || {};
      if (cpu.cores_logical) cores += Number(cpu.cores_logical) || 0;
      var mem = cap.memory || {};
      if (mem.total_mb) ramMb += Number(mem.total_mb) || 0;
      if (Array.isArray(cap.gpu)) gpuN += cap.gpu.length;
      var st = node.container_stats || {};
      if (Array.isArray(st.containers)) containers += st.containers.length;
    });
    if (!okNodes) return "No healthy nodes in this refresh.";
    return (
      "Totals (" +
      okNodes +
      " node" +
      (okNodes === 1 ? "" : "s") +
      "): " +
      cores +
      " logical cores · ~" +
      Math.round(ramMb / 1024) +
      " GiB RAM · " +
      gpuN +
      " GPU device(s) · " +
      containers +
      " running containers (capped per node)"
    );
  }

  function renderNodeSection(node) {
    var cap = nodeCap(node);
    var peerKey = node.scope === "peer" ? String(node.peer_id || "") : "";
    var sidMap = serviceContainerMap(node);
    var allowIds = knownServiceIds(node);
    var disabled = node.ok ? "" : " disabled";
    var gpuRows = "";
    (cap.gpu || []).forEach(function (d) {
      gpuRows +=
        "<tr><td>" +
        esc(d.vendor) +
        " #" +
        esc(d.index) +
        '</td><td class="fleet-mono">' +
        esc(d.name || "—") +
        '</td><td class="text-end">' +
        esc(fmtPct(d.utilization_pct)) +
        '</td><td class="text-end fleet-mono">' +
        esc(d.vram_used_mb != null ? d.vram_used_mb + " / " + (d.vram_total_mb || "?") + " MiB" : "—") +
        "</td></tr>";
    });
    if (!gpuRows) gpuRows = '<tr><td colspan="4" class="text-body-secondary">No GPU metrics</td></tr>';

    var svcRows = "";
    (node.services || []).forEach(function (svc) {
      var sid = String(svc.id || "");
      var st = svc.status || {};
      var running = st.services_running != null ? st.services_running : "—";
      var total = st.services_total != null ? st.services_total : "—";
      var err = st.last_error ? String(st.last_error).slice(0, 120) : "";
      var acts =
        allowIds[sid] && node.ok
          ? '<button type="button" class="btn btn-sm btn-outline-success me-1 fleet-cluster-start"' +
            disabled +
            ' data-svc-id="' +
            esc(sid) +
            '" data-node-scope="' +
            esc(node.scope) +
            '" data-peer-id="' +
            esc(peerKey) +
            '" data-node-label="' +
            esc(node.label || "") +
            '">Start</button>' +
            '<button type="button" class="btn btn-sm btn-outline-warning fleet-cluster-stop"' +
            disabled +
            ' data-svc-id="' +
            esc(sid) +
            '" data-node-scope="' +
            esc(node.scope) +
            '" data-peer-id="' +
            esc(peerKey) +
            '" data-node-label="' +
            esc(node.label || "") +
            '">Stop</button>'
          : '<span class="text-body-secondary">—</span>';
      svcRows +=
        "<tr>" +
        '<td class="fleet-mono">' +
        esc(sid) +
        "</td>" +
        '<td class="text-end fleet-mono">' +
        esc(String(running) + "/" + String(total)) +
        "</td>" +
        '<td class="small text-body-secondary">' +
        esc(err || "—") +
        "</td>" +
        '<td class="text-nowrap">' +
        acts +
        '<span class="fleet-mono small text-body-secondary ms-1 fleet-cluster-svc-msg" data-svc-id="' +
        esc(sid) +
        '"></span></td></tr>';
    });
    if (!svcRows) svcRows = '<tr><td colspan="4" class="text-body-secondary">No managed services</td></tr>';

    var containers = (node.container_stats && node.container_stats.containers) || [];
    var cRows = "";
    containers.forEach(function (c) {
      var name = String(c.container_name || "");
      var svc = sidMap[name] || "—";
      var mem =
        c.mem_usage_bytes != null && c.mem_limit_bytes != null
          ? fmtBytes(c.mem_usage_bytes) + " / " + fmtBytes(c.mem_limit_bytes)
          : "—";
      cRows +=
        "<tr>" +
        '<td class="fleet-mono">' +
        esc(name) +
        "</td>" +
        '<td class="fleet-mono">' +
        esc(svc) +
        '</td><td class="text-end fleet-mono">' +
        esc(fmtPct(c.cpu_pct)) +
        '</td><td class="text-end fleet-mono">' +
        esc(mem) +
        (c.mem_pct != null ? " (" + esc(fmtPct(c.mem_pct)) + ")" : "") +
        '</td><td class="text-end fleet-mono">' +
        esc(c.pids != null ? String(c.pids) : "—") +
        "</td></tr>";
    });
    if (!cRows) cRows = '<tr><td colspan="5" class="text-body-secondary">No running containers</td></tr>';
    var trunc =
      node.container_stats && node.container_stats.truncated
        ? '<p class="small text-warning mb-2">Container list truncated at 80 (reported ' +
          esc(String(node.container_stats.containers_total_reported || "?")) +
          " total).</p>"
        : "";

    return (
      '<section class="card border-secondary-subtle shadow-sm mb-3" data-fleet-cluster-node="' +
      esc(peerKey || "local") +
      '">' +
      '<div class="card-body">' +
      '<h3 class="h6 text-uppercase text-body-secondary mb-2">' +
      esc(node.label || node.node_id || "Node") +
      (node.scope === "peer" ? ' <span class="badge text-bg-secondary">peer</span>' : "") +
      "</h3>" +
      (node.errors && node.errors.length
        ? '<p class="small text-danger mb-2">' + esc(node.errors.join("; ")) + "</p>"
        : "") +
      '<p class="small text-body-secondary fleet-mono mb-2">Host CPU ' +
      esc(fmtPct((cap.cpu || {}).used_pct)) +
      " · RAM " +
      esc(fmtPct((cap.memory || {}).used_pct)) +
      "</p>" +
      '<div class="table-responsive mb-3"><table class="table table-sm table-bordered mb-0"><thead><tr>' +
      "<th>GPU</th><th>Name</th><th class=\"text-end\">Util</th><th class=\"text-end\">VRAM</th></tr></thead><tbody>" +
      gpuRows +
      "</tbody></table></div>" +
      '<h4 class="h6 text-uppercase text-body-secondary mb-1">Managed services</h4>' +
      '<div class="table-responsive mb-3"><table class="table table-sm table-hover mb-0"><thead><tr>' +
      "<th>Service</th><th class=\"text-end\">Running</th><th>Error</th><th>Actions</th></tr></thead><tbody>" +
      svcRows +
      "</tbody></table></div>" +
      '<h4 class="h6 text-uppercase text-body-secondary mb-1">Running containers</h4>' +
      trunc +
      '<div class="table-responsive"><table class="table table-sm table-hover mb-0"><thead><tr>' +
      "<th>Container</th><th>Service</th><th class=\"text-end\">CPU</th><th class=\"text-end\">Memory</th><th class=\"text-end\">PIDs</th>" +
      "</tr></thead><tbody>" +
      cRows +
      "</tbody></table></div></div></section>"
    );
  }

  function renderCluster(doc) {
    var strip = document.getElementById("fleet-cluster-mesh-strip");
    var totals = document.getElementById("fleet-cluster-totals");
    var nodesEl = document.getElementById("fleet-cluster-nodes");
    var meta = document.getElementById("fleet-cluster-meta");
    if (!strip || !nodesEl) return;
    var nodes = doc && doc.nodes ? doc.nodes : [];
    strip.innerHTML = renderMeshStrip(nodes);
    if (totals) totals.textContent = renderTotals(nodes);
    nodesEl.innerHTML = nodes.map(renderNodeSection).join("");
    if (meta) {
      var parts = ["observed " + new Date().toLocaleTimeString()];
      if (doc && doc.cached) parts.push("cached " + (doc.cache_age_s != null ? doc.cache_age_s + "s" : "?"));
      meta.textContent = parts.join(" · ");
    }
  }

  function refreshCluster(force) {
    var q = force ? "?refresh=1" : "";
    return fleetApi("/v1/cluster" + q)
      .then(function (res) {
        return res.json().then(function (doc) {
          return { res: res, doc: doc };
        });
      })
      .then(function (out) {
        var msg = document.getElementById("fleet-cluster-msg");
        if (!out.res.ok || !out.doc || out.doc.ok !== true) {
          if (msg) msg.textContent = "Cluster load failed.";
          return;
        }
        if (msg) msg.textContent = "";
        renderCluster(out.doc);
      })
      .catch(function (e) {
        var msg = document.getElementById("fleet-cluster-msg");
        if (msg) msg.textContent = String(e);
      });
  }

  function svcActionPath(scope, peerId, sid, action) {
    if (scope === "peer" && peerId) {
      return (
        "/v1/remote-peers/" +
        encodeURIComponent(peerId) +
        "/container-services/" +
        encodeURIComponent(sid) +
        "/" +
        action
      );
    }
    return "/v1/container-services/" + encodeURIComponent(sid) + "/" + action;
  }

  function postSvcAction(btn, action) {
    var sid = btn.getAttribute("data-svc-id");
    var scope = btn.getAttribute("data-node-scope") || "local";
    var peerId = btn.getAttribute("data-peer-id") || "";
    var label = btn.getAttribute("data-node-label") || "";
    if (!sid) return;
    if (action === "stop") {
      var ok = window.confirm("Stop service " + sid + " on " + (label || scope) + "?");
      if (!ok) return;
    }
    var path = svcActionPath(scope, peerId, sid, action);
    var msgEl = document.querySelector('.fleet-cluster-svc-msg[data-svc-id="' + sid + '"]');
    fleetApi(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
      .then(function (res) {
        return res.json().then(function (doc) {
          return { res: res, doc: doc };
        });
      })
      .then(function (out) {
        if (msgEl) {
          msgEl.textContent = out.res.ok && out.doc && out.doc.ok !== false ? action + " ok" : action + " failed";
        }
        return refreshCluster(true);
      })
      .catch(function (e) {
        if (msgEl) msgEl.textContent = String(e);
      });
  }

  function startPoll() {
    stopPoll();
    if (!clusterTabActive) return;
    pollTimer = window.setInterval(function () {
      refreshCluster(false);
    }, POLL_MS);
  }

  function stopPoll() {
    if (pollTimer != null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function onTabShown() {
    clusterTabActive = true;
    refreshCluster(false).then(startPoll);
  }

  function onTabHidden() {
    clusterTabActive = false;
    stopPoll();
  }

  function wireTab() {
    var btn = document.getElementById("fleet-tab-cluster-btn");
    var pane = document.getElementById("fleet-tab-cluster");
    if (!btn || !pane || typeof bootstrap === "undefined") return;
    btn.addEventListener("shown.bs.tab", onTabShown);
    document.querySelectorAll("#fleet-admin-tablist .nav-link").forEach(function (link) {
      if (link === btn) return;
      link.addEventListener("shown.bs.tab", onTabHidden);
    });
    if (pane.classList.contains("active") && pane.classList.contains("show")) onTabShown();
    var ref = document.getElementById("fleet-cluster-refresh-btn");
    if (ref) {
      ref.addEventListener("click", function () {
        refreshCluster(true);
      });
    }
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.classList) return;
      if (t.classList.contains("fleet-cluster-start")) {
        ev.preventDefault();
        postSvcAction(t, "start");
      } else if (t.classList.contains("fleet-cluster-stop")) {
        ev.preventDefault();
        postSvcAction(t, "stop");
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireTab);
  } else {
    wireTab();
  }
})();