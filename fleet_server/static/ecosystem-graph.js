/* Fleet admin — Ecosystem graph tab (reference architecture + live status). */
(function () {
  "use strict";

  var LS = "forgeFleetAdminToken";
  var POLL_MS = 10000;
  var pollTimer = null;
  var graphTabActive = false;
  var lastEco = null;
  var selectedId = null;

  var LAYER_ORDER = ["control", "reasoning", "edge", "product"];
  var COL_X = [32, 248, 464, 680];
  var NODE_W = 188;
  var NODE_H = 68;
  var GAP_Y = 12;

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
    return fetch(path, {
      method: opts.method || "GET",
      headers: headers,
      cache: "no-store",
    });
  }

  function statusStroke(state) {
    var s = String(state || "unknown");
    if (s === "running" || s === "up") return "#16a34a";
    if (s === "partial") return "#d97706";
    if (s === "error" || s === "down") return "#dc2626";
    return "#64748b";
  }

  function placementLine(comp) {
    if (!comp.placements || !comp.placements.length) return "Not on this mesh";
    return comp.placements
      .map(function (p) {
        return (p.node_label || p.node_id || "node") + " " + (p.state || "?");
      })
      .join(" · ");
  }

  function layoutNodes(components, layers) {
    var layerLabels = {};
    (layers || []).forEach(function (L) {
      layerLabels[L.id] = L.label || L.id;
    });
    var byLayer = {};
    LAYER_ORDER.forEach(function (lid) {
      byLayer[lid] = [];
    });
    (components || []).forEach(function (c) {
      var layer = c.layer || "product";
      if (!byLayer[layer]) byLayer[layer] = [];
      byLayer[layer].push(c);
    });
    var positions = {};
    var colHeights = LAYER_ORDER.map(function () {
      return 52;
    });
    var maxBottom = 0;
    LAYER_ORDER.forEach(function (layerId, col) {
      var x = COL_X[col];
      var y = 52;
      (byLayer[layerId] || []).forEach(function (comp) {
        positions[comp.id] = { x: x, y: y, w: NODE_W, h: NODE_H, comp: comp };
        y += NODE_H + GAP_Y;
        if (y > maxBottom) maxBottom = y;
      });
      colHeights[col] = y;
    });
    var width = COL_X[COL_X.length - 1] + NODE_W + 40;
    var height = Math.max(maxBottom + 24, 320);
    return { positions: positions, width: width, height: height, layerLabels: layerLabels };
  }

  function renderDetail(comp) {
    var el = document.getElementById("fleet-graph-detail");
    if (!el || !comp) return;
    var places =
      (comp.placements || []).length > 0
        ? "<ul class='list-unstyled mb-2 small'>" +
          comp.placements
            .map(function (p) {
              var counts =
                p.services_running != null
                  ? " " + esc(String(p.services_running)) + "/" + esc(String(p.services_total))
                  : "";
              return (
                "<li class='mb-1'><span class='fw-semibold'>" +
                esc(p.node_label || "?") +
                "</span> " +
                esc(p.state || "?") +
                (p.service_id ? " <span class='fleet-mono text-body-secondary'>" + esc(p.service_id) + "</span>" : "") +
                "<span class='fleet-mono text-body-secondary'>" +
                counts +
                "</span></li>"
              );
            })
            .join("") +
          "</ul>"
        : "<p class='small text-body-secondary'>Not on this mesh</p>";
    var links =
      (comp.connects_to || []).length > 0
        ? "<ul class='list-unstyled mb-0 small'>" +
          comp.connects_to
            .map(function (e) {
              return "<li class='mb-1'><span class='fw-semibold'>" + esc(e.id) + "</span> — " + esc(e.via) + "</li>";
            })
            .join("") +
          "</ul>"
        : "<p class='small text-body-secondary mb-0'>No outbound reference links</p>";
    el.innerHTML =
      "<h3 class='h6 mb-1'>" +
      esc(comp.label) +
      "</h3>" +
      "<p class='small mb-2'><span class='fleet-graph-status-badge'>" +
      esc(comp.status) +
      "</span></p>" +
      "<p class='small text-body-secondary'>" +
      esc(comp.summary || "") +
      "</p>" +
      "<h4 class='small text-uppercase text-body-secondary'>Placements</h4>" +
      places +
      "<h4 class='small text-uppercase text-body-secondary'>Connects to</h4>" +
      links;
  }

  function drawGraph(eco) {
    var host = document.getElementById("fleet-graph-svg-host");
    if (!host || !eco) return;
    var layout = layoutNodes(eco.components, eco.layers);
    var positions = layout.positions;
    var parts = [];
    parts.push(
      '<svg class="fleet-graph-svg" role="img" aria-label="Forge ecosystem graph" width="' +
        layout.width +
        '" height="' +
        layout.height +
        '" viewBox="0 0 ' +
        layout.width +
        " " +
        layout.height +
        '">'
    );
    LAYER_ORDER.forEach(function (lid, col) {
      var label = layout.layerLabels[lid] || lid;
      parts.push(
        '<text class="fleet-graph-layer-label" x="' +
          (COL_X[col] + NODE_W / 2) +
          '" y="22" text-anchor="middle">' +
          esc(label) +
          "</text>"
      );
    });
    parts.push('<g class="fleet-graph-edges">');
    (eco.components || []).forEach(function (comp) {
      var from = positions[comp.id];
      if (!from) return;
      (comp.connects_to || []).forEach(function (edge) {
        var to = positions[edge.id];
        if (!to) return;
        var x1 = from.x + from.w;
        var y1 = from.y + from.h / 2;
        var x2 = to.x;
        var y2 = to.y + to.h / 2;
        var mx = (x1 + x2) / 2;
        parts.push(
          '<path class="fleet-graph-edge" d="M' +
            x1 +
            " " +
            y1 +
            " C " +
            mx +
            " " +
            y1 +
            ", " +
            mx +
            " " +
            y2 +
            ", " +
            x2 +
            " " +
            y2 +
            '" fill="none" stroke-width="1.5"><title>' +
            esc(edge.via) +
            "</title></path>"
        );
      });
    });
    parts.push("</g>");
    parts.push('<g class="fleet-graph-nodes">');
    (eco.components || []).forEach(function (comp) {
      var p = positions[comp.id];
      if (!p) return;
      var stroke = statusStroke(comp.status);
      var sel = selectedId === comp.id ? " fleet-graph-node--selected" : "";
      parts.push(
        '<g class="fleet-graph-node' +
          sel +
          '" data-graph-id="' +
          esc(comp.id) +
          '" tabindex="0" role="button" aria-label="' +
          esc(comp.label) +
          " " +
          esc(comp.status) +
          '">' +
          '<rect x="' +
          p.x +
          '" y="' +
          p.y +
          '" width="' +
          p.w +
          '" height="' +
          p.h +
          '" rx="8" ry="8" class="fleet-graph-node-rect" stroke="' +
          stroke +
          '"/>' +
          '<text class="fleet-graph-node-title" x="' +
          (p.x + 10) +
          '" y="' +
          (p.y + 22) +
          '">' +
          esc(comp.label) +
          "</text>" +
          '<text class="fleet-graph-node-status" x="' +
          (p.x + 10) +
          '" y="' +
          (p.y + 38) +
          '">' +
          esc(comp.status) +
          "</text>" +
          '<text class="fleet-graph-node-placements" x="' +
          (p.x + 10) +
          '" y="' +
          (p.y + 54) +
          '">' +
          esc(placementLine(comp).slice(0, 72)) +
          (placementLine(comp).length > 72 ? "…" : "") +
          "</text>" +
          "</g>"
      );
    });
    parts.push("</g></svg>");
    host.innerHTML = parts.join("");
    host.querySelectorAll(".fleet-graph-node").forEach(function (node) {
      node.addEventListener("click", function () {
        selectedId = node.getAttribute("data-graph-id");
        var comp = (eco.components || []).filter(function (c) {
          return c.id === selectedId;
        })[0];
        drawGraph(eco);
        renderDetail(comp);
      });
      node.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          node.click();
        }
      });
    });
    if (selectedId) {
      var selComp = (eco.components || []).filter(function (c) {
        return c.id === selectedId;
      })[0];
      if (selComp) renderDetail(selComp);
    }
  }

  function renderOther(other) {
    var el = document.getElementById("fleet-graph-other");
    if (!el) return;
    if (!other || !other.length) {
      el.textContent = "";
      el.classList.add("d-none");
      return;
    }
    el.classList.remove("d-none");
    el.textContent =
      "Other managed services: " +
      other
        .map(function (row) {
          return (row.node_label || "?") + "/" + (row.service_id || "?") + " (" + (row.state || "?") + ")";
        })
        .join(", ");
  }

  function refreshGraph(force) {
    var q = force ? "?refresh=1" : "";
    return fleetApi("/v1/cluster" + q)
      .then(function (res) {
        return res.json();
      })
      .then(function (doc) {
        var msg = document.getElementById("fleet-graph-msg");
        var meta = document.getElementById("fleet-graph-meta");
        if (!doc || doc.ok !== true) {
          if (msg) msg.textContent = "Graph load failed.";
          return;
        }
        if (msg) msg.textContent = "";
        lastEco = doc.ecosystem;
        drawGraph(lastEco);
        renderOther(lastEco && lastEco.other_services);
        if (meta) {
          meta.textContent =
            "observed " + new Date().toLocaleTimeString() + (doc.cached ? " · cached " + (doc.cache_age_s || "?") + "s" : "");
        }
      })
      .catch(function (e) {
        var msg = document.getElementById("fleet-graph-msg");
        if (msg) msg.textContent = String(e);
      });
  }

  function startPoll() {
    stopPoll();
    if (!graphTabActive) return;
    pollTimer = window.setInterval(function () {
      refreshGraph(false);
    }, POLL_MS);
  }

  function stopPoll() {
    if (pollTimer != null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function onTabShown() {
    graphTabActive = true;
    refreshGraph(false).then(startPoll);
  }

  function onTabHidden() {
    graphTabActive = false;
    stopPoll();
  }

  function wireTab() {
    var btn = document.getElementById("fleet-tab-graph-btn");
    var pane = document.getElementById("fleet-tab-graph");
    if (!btn || !pane) return;
    btn.addEventListener("shown.bs.tab", onTabShown);
    document.querySelectorAll("#fleet-admin-tablist .nav-link").forEach(function (link) {
      if (link === btn) return;
      link.addEventListener("shown.bs.tab", onTabHidden);
    });
    if (pane.classList.contains("active") && pane.classList.contains("show")) onTabShown();
    var ref = document.getElementById("fleet-graph-refresh-btn");
    if (ref) {
      ref.addEventListener("click", function () {
        refreshGraph(true);
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireTab);
  } else {
    wireTab();
  }
})();