/* Fleet Performance Intelligence — Benchmarks tab (GET /v1/mesh/benchmarks/score). */
(function () {
  "use strict";

  var STAGES = ["postgresql", "duckdb", "sqlite", "numpy", "nlp"];
  var LS_BASELINE = "forgeFpiBaseline";
  var LS_SNAPSHOTS = "forgeFpiIncludeSnapshots";
  var LS_WEIGHTS = "forgeFpiWeights";

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtScore(n) {
    if (n == null || n === "") return "—";
    return Number(n).toFixed(1);
  }

  function fmtSpeedup(n) {
    if (n == null) return "—";
    return Number(n).toFixed(2) + "×";
  }

  function readPolicy(defaultBaseline) {
    var baseline = defaultBaseline || "local";
    try {
      var b = (localStorage.getItem(LS_BASELINE) || "").trim();
      if (b) baseline = b;
    } catch (_e) {}
    var includeSnapshots = false;
    try {
      includeSnapshots = localStorage.getItem(LS_SNAPSHOTS) === "1";
    } catch (_e2) {}
    var weights = null;
    try {
      var w = (localStorage.getItem(LS_WEIGHTS) || "").trim();
      if (w) weights = w;
    } catch (_e3) {}
    return { baseline: baseline, include_snapshots: includeSnapshots, weights: weights };
  }

  function writePolicy(p) {
    try {
      localStorage.setItem(LS_BASELINE, p.baseline || "local");
      localStorage.setItem(LS_SNAPSHOTS, p.include_snapshots ? "1" : "0");
      if (p.weights) localStorage.setItem(LS_WEIGHTS, p.weights);
    } catch (_e) {}
  }

  function scoreQuery(defaultBaseline) {
    var p = readPolicy(defaultBaseline);
    var q = "baseline=" + encodeURIComponent(p.baseline);
    q += "&include_snapshots=" + (p.include_snapshots ? "1" : "0");
    if (p.weights) q += "&weights=" + encodeURIComponent(p.weights);
    return q;
  }

  function heroComposite(doc) {
    var cluster = doc.cluster || {};
    return cluster.composite != null ? cluster.composite : cluster.composite_confirmed;
  }

  function renderHero(doc) {
    var root = document.getElementById("fleet-perf-hero");
    if (!root) return;
    var cluster = doc.cluster || {};
    var baseline = doc.baseline || {};
    var composite = heroComposite(doc);
    var confirmed = cluster.composite_confirmed;
    var withSnap = cluster.composite_with_snapshots;
    var mult = composite != null && baseline.status === "measured" ? (Number(composite) / 100).toFixed(2) : "—";
    root.innerHTML =
      '<div class="display-6 fw-semibold">' + esc(fmtScore(composite)) + "</div>" +
      '<p class="mb-1"><strong>Modeled cluster capacity</strong> · baseline <code class="fleet-mono">' +
      esc(baseline.label || baseline.node_id || "—") + "</code>" +
      (baseline.status === "temporary_fallback" ? ' <span class="badge text-bg-warning">provisional reference</span>' : "") +
      "</p>" +
      '<p class="small text-body-secondary mb-2">' + esc(mult) + "× reference (100 = baseline node composite). " +
      "Sum of standalone multi-worker rates — not verified distributed throughput.</p>" +
      '<p class="small mb-0">Confirmed live nodes: <strong>' + esc(fmtScore(confirmed)) +
      "</strong> · including saved snapshots: <strong>" + esc(fmtScore(withSnap)) + "</strong></p>";
  }

  function renderInsights(doc) {
    var root = document.getElementById("fleet-perf-insights");
    if (!root) return;
    var list = doc.insights || [];
    if (!list.length) {
      root.innerHTML = '<p class="small text-body-secondary mb-0">No priority findings.</p>';
      return;
    }
    root.innerHTML = list
      .map(function (item) {
        var sev = item.severity === "blocker" ? "danger" : item.severity === "attention" ? "warning" : "secondary";
        return (
          '<div class="card border-' + sev + '-subtle mb-2"><div class="card-body py-2">' +
          '<div class="small text-uppercase text-body-secondary">' + esc(item.rule_id) + "</div>" +
          "<p class=\"small mb-1\"><strong>Observed:</strong> " + esc(item.observation) + "</p>" +
          "<p class=\"small mb-1\"><strong>Means:</strong> " + esc(item.meaning) + "</p>" +
          "<p class=\"small mb-0\"><strong>Next:</strong> " + esc(item.recommended_action) + "</p></div></div>"
        );
      })
      .join("");
  }

  function renderComponents(doc) {
    var root = document.getElementById("fleet-perf-components");
    if (!root) return;
    var comps = doc.components || {};
    var html = '<div class="row g-2">';
    STAGES.forEach(function (sid) {
      var c = comps[sid] || {};
      html +=
        '<div class="col-sm-6 col-lg-4"><div class="card h-100 border-secondary-subtle"><div class="card-body py-2">' +
        "<strong>" + esc(c.label || sid) + "</strong>" +
        '<div class="fs-5">' + esc(fmtScore(c.cluster_index)) + "</div>" +
        '<div class="small text-body-secondary">weight " + esc(String(Math.round((c.weight || 0) * 100))) +
        "% · contrib " + esc(fmtScore(c.weighted_contribution)) + " · " + esc(c.unit || "") + "</div></div></div></div>";
    });
    html += "</div>";
    root.innerHTML = html;
  }

  function renderSpeedupMatrix(doc) {
    var root = document.getElementById("fleet-perf-speedup-matrix");
    if (!root) return;
    var nodes = doc.nodes || [];
    var html =
      '<div class="table-responsive fleet-perf-scroll"><table class="table table-sm table-bordered mb-0">' +
      "<thead><tr><th scope=\"col\">Node</th>";
    STAGES.forEach(function (sid) {
      html += "<th scope=\"col\">" + esc(sid) + "</th>";
    });
    html += "</tr></thead><tbody>";
    nodes.forEach(function (node) {
      html += "<tr><th scope=\"row\">" + esc(node.label || node.node_id) + "</th>";
      var comps = node.components || {};
      STAGES.forEach(function (sid) {
        var c = comps[sid] || {};
        html += "<td title=\"" + esc(JSON.stringify(c)) + "\">" + esc(fmtSpeedup(c.speedup)) + "</td>";
      });
      html += "</tr>";
    });
    html += "</tbody></table></div>";
    root.innerHTML = html;
  }

  function renderWorkloads(doc) {
    var root = document.getElementById("fleet-perf-workloads-pane");
    if (!root) return;
    var nodes = doc.nodes || [];
    var html = "";
    STAGES.forEach(function (sid) {
      html += "<h4 class=\"h6 mt-3\">" + esc(sid) + "</h4>";
      html += '<div class="table-responsive fleet-perf-scroll"><table class="table table-sm"><thead><tr>' +
        "<th>Node</th><th>1 worker</th><th>Max workers</th><th>Speedup</th><th>Component score</th></tr></thead><tbody>";
      nodes.forEach(function (node) {
        var c = (node.components || {})[sid] || {};
        html +=
          "<tr><td>" + esc(node.label || node.node_id) + "</td>" +
          "<td>" + (c.single_rate != null ? esc(String(c.single_rate)) : "Not measured") + "</td>" +
          "<td>" + (c.max_rate != null ? esc(String(c.max_rate)) + (c.max_workers ? " · " + c.max_workers + " workers" : "") : "Not measured") + "</td>" +
          "<td>" + esc(fmtSpeedup(c.speedup)) + "</td>" +
          "<td>" + esc(fmtScore(c.index)) + "</td></tr>";
      });
      html += "</tbody></table></div>";
    });
    root.innerHTML = html;
  }

  function renderScoringControls(doc, onChange) {
    var root = document.getElementById("fleet-perf-scoring-pane");
    if (!root) return;
    var nodes = doc.nodes || [];
    var baseline = (doc.baseline && doc.baseline.node_id) || "local";
    var policy = readPolicy(baseline);
    var opts = nodes
      .filter(function (n) {
        return n.composite != null;
      })
      .map(function (n) {
        return '<option value="' + esc(n.node_id) + '"' + (n.node_id === policy.baseline ? " selected" : "") + ">" + esc(n.label || n.node_id) + "</option>";
      })
      .join("");
    var w = doc.weights_display_percent || {};
    root.innerHTML =
      '<div class="row g-3"><div class="col-md-6">' +
      '<label class="form-label small" for="fleet-fpi-baseline">Baseline node</label>' +
      '<select id="fleet-fpi-baseline" class="form-select form-select-sm">' + opts + "</select>" +
      '<div class="form-check mt-2"><input class="form-check-input" type="checkbox" id="fleet-fpi-snapshots"' +
      (policy.include_snapshots ? " checked" : "") + '><label class="form-check-label small" for="fleet-fpi-snapshots">Include saved snapshots in headline score</label></div>' +
      "</div><div class=\"col-md-6\"><p class=\"small text-body-secondary\">Weights (percent, normalized to 100 on apply).</p>" +
      STAGES.map(function (sid) {
        var val = w[sid] != null ? w[sid] : 0;
        return '<label class="small d-block">' + esc(sid) +
          ' <input type="number" min="0" max="100" step="1" class="form-control form-control-sm d-inline-block w-auto fleet-fpi-weight" data-stage="' +
          esc(sid) + '" value="' + esc(String(Math.round(val))) + '"></label>';
      }).join("") +
      '<button type="button" class="btn btn-sm btn-outline-primary mt-2" id="fleet-fpi-apply">Apply scoring settings</button></div></div>' +
      '<div id="fleet-perf-matrix" class="mt-3"></div>';

    var matrix = document.getElementById("fleet-perf-matrix");
    if (matrix) {
      var html =
        '<table class="table table-sm table-bordered"><thead><tr><th>Node</th>';
      STAGES.forEach(function (s) {
        html += "<th>" + esc(s) + "</th>";
      });
      html += "<th>Composite</th></tr></thead><tbody>";
      nodes.forEach(function (node) {
        html += "<tr><th scope=\"row\">" + esc(node.label || node.node_id) + "</th>";
        STAGES.forEach(function (sid) {
          var c = (node.components || {})[sid] || {};
          html += "<td>" + esc(fmtScore(c.index)) + "</td>";
        });
        html += "<td>" + esc(fmtScore(node.composite)) + (node.included_in_cluster ? "" : " (excluded)") + "</td></tr>";
      });
      html += "</tbody></table>";
      matrix.innerHTML = html;
    }

    var apply = document.getElementById("fleet-fpi-apply");
    if (apply && onChange) {
      apply.onclick = function () {
        var baseSel = document.getElementById("fleet-fpi-baseline");
        var snap = document.getElementById("fleet-fpi-snapshots");
        var parts = [];
        document.querySelectorAll(".fleet-fpi-weight").forEach(function (inp) {
          parts.push(String(inp.value || "0"));
        });
        writePolicy({
          baseline: baseSel && baseSel.value ? baseSel.value : baseline,
          include_snapshots: !!(snap && snap.checked),
          weights: parts.join(","),
        });
        onChange();
      };
    }
  }

  function renderNodes(doc) {
    var root = document.getElementById("fleet-perf-nodes-pane");
    if (!root) return;
    var nodes = doc.nodes || [];
    var html =
      '<label class="small" for="fleet-fpi-node-select">Node</label><select id="fleet-fpi-node-select" class="form-select form-select-sm mb-2">';
    nodes.forEach(function (n, i) {
      html += '<option value="' + esc(n.node_id) + '"' + (i === 0 ? " selected" : "") + ">" + esc(n.label || n.node_id) + "</option>";
    });
    html += '</select><div id="fleet-fpi-node-detail"></div>';
    root.innerHTML = html;
    var sel = document.getElementById("fleet-fpi-node-select");
    function paint() {
      var detail = document.getElementById("fleet-fpi-node-detail");
      if (!detail || !sel) return;
      var node = nodes.find(function (n) {
        return n.node_id === sel.value;
      });
      if (!node) return;
      detail.innerHTML =
        "<p class=\"small\">Evidence: <strong>" + esc(node.evidence) + "</strong> · Hardware mark (separate): " +
        esc(node.hardware_score != null ? String(node.hardware_score) : "—") + "</p>" +
        '<table class="table table-sm"><thead><tr><th>Stage</th><th>Score</th><th>Speedup</th></tr></thead><tbody>' +
        STAGES.map(function (sid) {
          var c = (node.components || {})[sid] || {};
          return "<tr><td>" + esc(sid) + "</td><td>" + esc(fmtScore(c.index)) + "</td><td>" + esc(fmtSpeedup(c.speedup)) + "</td></tr>";
        }).join("") +
        "</tbody></table>";
    }
    if (sel) sel.onchange = paint;
    paint();
  }

  function renderLegacyStageGrid(comparisonDoc) {
    var root = document.getElementById("fleet-bench-measure-body");
    if (!root || !comparisonDoc || !window.forgeFleetBenchmarksView) return;
    window.forgeFleetBenchmarksView.render(comparisonDoc, {});
    var grid = document.getElementById("fleet-bench-measure-body");
    if (grid && root !== grid) root.innerHTML = grid.innerHTML;
  }

  function syncPageTitle() {
    var title = document.getElementById("fleet-bench-page-title");
    if (!title) return;
    title.textContent = "Forge Performance Intelligence";
  }

  function adminBenchmarksUrl(base) {
    var root = String(base || "").replace(/\/+$/, "");
    if (!root) return "";
    return root + "/admin/#benchmarks";
  }

  function renderConsoles(peers) {
    var root = document.getElementById("fleet-bench-consoles");
    if (!root) return;
    var here = window.location.origin + "/admin/#benchmarks";
    var links = [
      '<span class="me-2"><strong>This console</strong> <a href="' + esc(here) + '">' + esc(here) + "</a></span>",
    ];
    (peers || []).forEach(function (peer) {
      var url = adminBenchmarksUrl(peer.base_url);
      if (!url) return;
      var label = peer.label || peer.id || "peer";
      links.push(
        '<span class="me-2"><strong>' + esc(label) + "</strong> " +
        '<a href="' + esc(url) + '" rel="noopener noreferrer">' + esc(url) + "</a></span>"
      );
    });
    root.innerHTML =
      "<p class=\"mb-1\"><strong>Fleet consoles</strong></p><p class=\"mb-0\">" + links.join(" · ") + "</p>";
  }

  function render(doc, opts) {
    if (!doc || !doc.ok) return;
    opts = opts || {};
    syncPageTitle();
    if (opts.peers) renderConsoles(opts.peers);
    renderHero(doc);
    renderComponents(doc);
    renderInsights(doc);
    renderSpeedupMatrix(doc);
    renderWorkloads(doc);
    renderScoringControls(doc, opts.onPolicyChange);
    renderNodes(doc);
    if (opts.comparisonDoc) {
      if (window.forgeFleetBenchmarksView && typeof window.forgeFleetBenchmarksView.render === "function") {
        window.forgeFleetBenchmarksView.render(opts.comparisonDoc, { peers: opts.peers || [] });
      }
    }
  }

  window.forgeFleetPerformanceView = {
    render: render,
    readPolicy: readPolicy,
    writePolicy: writePolicy,
    scoreQuery: scoreQuery,
  };
})();
