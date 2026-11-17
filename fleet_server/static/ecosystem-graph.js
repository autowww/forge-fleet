/* Fleet admin — presence matrix. Rows are nodes, columns are declared purposes. */
(function () {
  "use strict";

  var LS = "forgeFleetAdminToken";
  var POLL_MS = 10000;
  var pollTimer = null;
  var graphTabActive = false;
  var selectedKey = "";

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

  function kindMark(kind) {
    if (kind === "worker") return "W";
    if (kind === "integration") return "I";
    return "S";
  }

  function kindWord(kind) {
    if (kind === "worker") return "worker";
    if (kind === "integration") return "integration";
    return "service";
  }

  function stroke(state) {
    var s = String(state || "");
    if (s === "running" || s === "up") return "fleet-graph-st-running";
    if (s === "partial") return "fleet-graph-st-partial";
    if (s === "error" || s === "down") return "fleet-graph-st-error";
    if (s === "stale") return "fleet-graph-st-stale";
    return "fleet-graph-st-neutral";
  }

  function cellMap(doc) {
    var map = {};
    (doc.cells || []).forEach(function (cell) {
      map[cell.node_id + "\n" + cell.purpose] = cell.instances || [];
    });
    return map;
  }

  function renderDetail(inst, nodeId, purpose) {
    var el = document.getElementById("fleet-graph-detail");
    if (!el || !inst) return;
    el.innerHTML =
      "<h3 class='h6 mb-1'>" +
      esc(inst.label) +
      "</h3>" +
      "<p class='small mb-2'><span class='fleet-graph-status-badge " +
      stroke(inst.status) +
      "'>" +
      esc(inst.status) +
      "</span> <span class='fleet-mono'>" +
      esc(kindWord(inst.kind)) +
      "</span></p>" +
      "<p class='small mb-1'><span class='text-body-secondary'>Node</span> " +
      esc(nodeId) +
      "</p>" +
      "<p class='small mb-1'><span class='text-body-secondary'>Purpose</span> " +
      esc(purpose) +
      "</p>" +
      "<p class='small mb-1'><span class='text-body-secondary'>Auth</span> " +
      esc(inst.auth_label || inst.auth) +
      "</p>" +
      (inst.detail
        ? "<p class='small text-body-secondary mb-1'>" + esc(inst.detail) + "</p>"
        : "") +
      "<p class='small fleet-mono text-body-secondary mb-0'>seen " +
      esc(new Date((inst.seen_epoch || 0) * 1000).toLocaleTimeString()) +
      "</p>";
  }

  function draw(doc) {
    var host = document.getElementById("fleet-graph-svg-host");
    if (!host || !doc) return;
    var nodes = doc.nodes || [];
    var purposes = doc.purposes || [];
    if (!nodes.length || !purposes.length) {
      host.innerHTML = "<p class='small text-body-secondary mb-0'>No heartbeats yet. Products announce themselves to this Fleet.</p>";
      return;
    }
    var map = cellMap(doc);
    var html = ["<table class='fleet-graph-matrix'><thead><tr><th>Node</th>"];
    purposes.forEach(function (p) {
      html.push("<th>" + esc(p) + "</th>");
    });
    html.push("</tr></thead><tbody>");
    nodes.forEach(function (node) {
      html.push("<tr><th scope='row'>" + esc(node.label || node.id) + (node.local ? " · local" : "") + "</th>");
      purposes.forEach(function (purpose) {
        var insts = map[node.id + "\n" + purpose] || [];
        html.push("<td>");
        insts.forEach(function (inst) {
          var key = node.id + "|" + purpose + "|" + inst.id;
          var sel = key === selectedKey ? " fleet-graph-chip--selected" : "";
          html.push(
            "<button type='button' class='fleet-graph-chip " +
              stroke(inst.status) +
              sel +
              "' data-key='" +
              esc(key) +
              "' data-node='" +
              esc(node.id) +
              "' data-purpose='" +
              esc(purpose) +
              "' data-id='" +
              esc(inst.id) +
              "'><span class='fleet-graph-kind'>" +
              kindMark(inst.kind) +
              "</span> " +
              esc(inst.label) +
              " <span class='fleet-graph-status-word'>" +
              esc(inst.status) +
              "</span></button>"
          );
        });
        html.push("</td>");
      });
      html.push("</tr>");
    });
    html.push("</tbody></table>");
    host.innerHTML = html.join("");
    host.querySelectorAll(".fleet-graph-chip").forEach(function (btn) {
      btn.addEventListener("click", function () {
        selectedKey = btn.getAttribute("data-key") || "";
        var nodeId = btn.getAttribute("data-node");
        var purpose = btn.getAttribute("data-purpose");
        var id = btn.getAttribute("data-id");
        var inst = (map[nodeId + "\n" + purpose] || []).filter(function (row) {
          return row.id === id;
        })[0];
        renderDetail(inst, nodeId, purpose);
        draw(doc);
      });
    });
  }

  function refreshGraph() {
    return fetch("/v1/presence", { headers: authHeaders(), cache: "no-store" })
      .then(function (res) {
        return res.json();
      })
      .then(function (doc) {
        var msg = document.getElementById("fleet-graph-msg");
        var meta = document.getElementById("fleet-graph-meta");
        if (!doc || doc.ok !== true) {
          if (msg) msg.textContent = "Presence load failed.";
          return;
        }
        if (msg) msg.textContent = "";
        draw(doc);
        if (meta) meta.textContent = "observed " + new Date().toLocaleTimeString();
      })
      .catch(function (e) {
        var msg = document.getElementById("fleet-graph-msg");
        if (msg) msg.textContent = String(e);
      });
  }

  function startPoll() {
    stopPoll();
    if (!graphTabActive) return;
    pollTimer = window.setInterval(refreshGraph, POLL_MS);
  }

  function stopPoll() {
    if (pollTimer != null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function onTabShown() {
    graphTabActive = true;
    refreshGraph();
    startPoll();
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
    if (ref) ref.addEventListener("click", refreshGraph);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wireTab);
  else wireTab();
})();