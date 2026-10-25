/* Forge admin — Benchmarks tab one-page layout (data from GET /v1/mesh/benchmarks). */
(function () {
  "use strict";

  var STAGE_KEYS = [
    ["postgres", "PostgreSQL", "bundles/s"],
    ["duckdb", "DuckDB", "bundles/s"],
    ["sqlite", "SQLite", "bundles/s"],
    ["compute", "NumPy", "rows/s"],
    ["nlp", "NLP 1 GiB", "docs/s"],
  ];

  var PROFILE_HINTS = {
    standard: "Profile standard: full fixture; two-thread rates feed the composite.",
    "host-max-cores": "Profile host-max-cores: same dataset at physical core count; saved beside standard, not the composite.",
    "host-max-threads": "Profile host-max-threads: same dataset at hardware thread count (suite caps workers at 64).",
    stress: "Profile stress: oversubscribed run; separate stress score, not the composite.",
    full: "Profile full: standard, both host-max widths, then stress.",
    smoke: "Profile smoke: short install check; replaces displayed result; not the comparison profile.",
    micro: "Profile micro: shortest check; replaces displayed result; not the comparison profile.",
  };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function hasNumeric(v) {
    if (v === null || v === undefined || v === "") return false;
    var n = Number(v);
    return isFinite(n);
  }

  function fmtStageRate(name, n) {
    if (!hasNumeric(n)) return "—";
    var v = Number(n);
    if (name === "compute") return (v / 1000000).toFixed(1) + "M rows/s";
    if (name === "nlp") return v.toFixed(0) + " docs/s";
    return v.toFixed(2) + " bundles/s";
  }

  function fmtSeconds(n) {
    if (!hasNumeric(n)) return "—";
    return Number(n).toFixed(1) + "s";
  }

  function scoreCell(n) {
    if (!hasNumeric(n)) return "—";
    return String(Math.round(Number(n)));
  }

  function peerLabel(row) {
    var who = row.label || row.peer_id || "peer";
    if (row.node_id && row.node_id !== who) who += " (" + row.node_id + ")";
    return who;
  }

  function evidencePill(row, fms, doc) {
    var bits = [];
    if (row.from_saved) bits.push("saved snapshot");
    if (row.live_error) bits.push("live: " + row.live_error);
    var profile = fms.profile || "";
    if (profile && profile !== "standard") bits.push("profile " + profile + " (not composite source)");
    else if (profile === "standard") bits.push("standard");
    if (fms.composite_nlp === false && doc.reference_nlp) bits.push("partial · NLP missing");
    else if (fms.status === "passed" && fms.stages) bits.push("stages recorded");
    else if (fms.status) bits.push(fms.status);
    if (!bits.length) bits.push("no Market Studio run");
    var warn = bits.some(function (b) {
      return b.indexOf("partial") >= 0 || b.indexOf("not composite") >= 0 || b.indexOf("saved") >= 0;
    });
    return '<span class="badge text-bg-' + (warn ? "warning" : "secondary") + '">' + esc(bits.join(" · ")) + "</span>";
  }

  function doubleRate(row, stageKey) {
    var fms = row.fmsbench || {};
    var inner = fms.stages && fms.stages.stages ? fms.stages.stages : {};
    var stage = inner[stageKey] || {};
    var two = stage.double && typeof stage.double === "object" ? stage.double : {};
    return hasNumeric(two.rate) ? Number(two.rate) : null;
  }

  function countStagesPresent(rows) {
    var max = 0;
    rows.forEach(function (row) {
      var n = 0;
      STAGE_KEYS.forEach(function (pair) {
        if (doubleRate(row, pair[0]) != null) n += 1;
      });
      if (n > max) max = n;
    });
    return max;
  }

  function nlpMissingOnAny(rows) {
    return rows.some(function (row) {
      return doubleRate(row, "nlp") == null && (row.fmsbench || {}).stages;
    });
  }

  function renderAnswers(doc) {
    var root = document.getElementById("fleet-bench-answers");
    if (!root) return;
    var rows = doc && doc.rows ? doc.rows : [];
    if (!rows.length) {
      root.innerHTML = '<div class="col-12 small text-body-secondary">No peers configured.</div>';
      return;
    }
    var refId = (doc && doc.reference_peer_id) || "local";
    var cluster = doc && doc.cluster_score != null ? doc.cluster_score : "—";
    var stageCount = countStagesPresent(rows);
    var nlpGap = nlpMissingOnAny(rows);
    var savedCount = rows.filter(function (r) { return r.from_saved; }).length;
    var measured = rows.filter(function (r) {
      var fms = r.fmsbench || {};
      return fms.composite_score != null || (r.fleet || {}).fleet_mark != null;
    }).length;

    var cards = [
      {
        title: "Reference (100)",
        body: "Composite 100 = this server's two-thread Market Studio standard rates (<code class=\"fleet-mono\">" + esc(refId) + "</code>).",
      },
      {
        title: "Additive capacity index",
        body: "Cluster <strong>" + esc(String(cluster)) + "</strong> — sum of comparable composites in reference units. Not verified distributed throughput.",
      },
      {
        title: "Nodes",
        body: measured + " of " + rows.length + " with a saved hardware or Market Studio result" +
          (savedCount ? "; " + savedCount + " from saved snapshot" : "") + ".",
      },
      {
        title: "Stage coverage",
        body: (stageCount ? stageCount : "0") + " / 5 workloads with two-thread rates" +
          (nlpGap ? "; NLP <strong>Not measured</strong> on at least one node" : "") + ".",
      },
    ];
    root.innerHTML = cards
      .map(function (c) {
        return (
          '<div class="col-sm-6 col-xl-3"><div class="card border-secondary-subtle h-100"><div class="card-body">' +
          '<div class="small text-uppercase text-body-secondary mb-1">' + esc(c.title) + "</div>" +
          '<div class="small">' + c.body + "</div></div></div></div>"
        );
      })
      .join("");
  }

  function renderWorkloads(doc) {
    var root = document.getElementById("fleet-bench-workloads");
    if (!root) return;
    var rows = doc && doc.rows ? doc.rows : [];
    if (!rows.length) {
      root.textContent = "No nodes to compare.";
      return;
    }
    var refId = (doc && doc.reference_peer_id) || "local";
    var html = "";
    STAGE_KEYS.forEach(function (pair) {
      var key = pair[0];
      var label = pair[1];
      var rates = rows.map(function (row) {
        return { label: peerLabel(row), rate: doubleRate(row, key), ref: row.peer_id === refId };
      });
      var measurable = rates.filter(function (r) { return r.rate != null; });
      if (!measurable.length) {
        html +=
          '<div class="mb-4"><strong>' + esc(label) + "</strong>" +
          '<p class="small text-body-secondary mb-0">Not measured on any node.</p></div>';
        return;
      }
      var max = Math.max.apply(null, measurable.map(function (r) { return r.rate; }));
      var leader = "";
      if (measurable.length >= 2) {
        var sorted = measurable.slice().sort(function (a, b) { return b.rate - a.rate; });
        var top = sorted[0];
        var second = sorted[1];
        if (second.rate > 0) {
          leader = top.label + " leads · " + (top.rate / second.rate).toFixed(2) + "× vs next";
        }
      }
      html += '<div class="mb-4"><div class="d-flex justify-content-between align-items-baseline gap-2 flex-wrap">' +
        "<strong>" + esc(label) + "</strong>" +
        (leader ? '<span class="small text-body-secondary">' + esc(leader) + "</span>" : "") +
        "</div>";
      rates.forEach(function (r) {
        if (r.rate == null) {
          html +=
            '<div class="mt-2 small"><span class="fw-semibold">' + esc(r.label) +
            (r.ref ? " (reference)" : "") + '</span> — Not measured</div>';
          return;
        }
        var pct = max > 0 ? Math.round(100 * r.rate / max) : 0;
        html +=
          '<div class="mt-2"><div class="d-flex justify-content-between small mb-1">' +
          "<span>" + esc(r.label) + (r.ref ? ' <span class="text-body-secondary">(reference)</span>' : "") + "</span>" +
          "<span>" + esc(fmtStageRate(key, r.rate)) + "</span></div>" +
          '<div class="progress" style="height:8px" role="progressbar" aria-valuenow="' + pct + '" aria-valuemin="0" aria-valuemax="100">' +
          '<div class="progress-bar" style="width:' + pct + '%"></div></div></div>';
      });
      html += "</div>";
    });
    root.innerHTML = html;
  }

  function renderNodes(doc) {
    var root = document.getElementById("fleet-bench-nodes");
    var capNote = document.getElementById("fleet-bench-thread-cap-note");
    if (!root) return;
    var rows = doc && doc.rows ? doc.rows : [];
    if (!rows.length) {
      root.textContent = "No nodes.";
      return;
    }
    var refId = (doc && doc.reference_peer_id) || "local";
    var showCap = false;
    var html =
      '<table class="table table-sm table-bordered mb-0"><thead><tr>' +
      "<th>Node</th><th>Evidence</th><th>Composite</th><th>Hardware</th>" +
      "<th>PostgreSQL</th><th>DuckDB</th><th>SQLite</th><th>NumPy</th><th>NLP</th>" +
      "<th>Cores</th><th>Threads</th></tr></thead><tbody>";
    rows.forEach(function (row) {
      var fms = row.fmsbench || {};
      var fleet = row.fleet || {};
      var cap = row.capacity || {};
      var composite = scoreCell(fms.composite_score);
      if (row.peer_id === refId) composite += ' <span class="text-body-secondary">(100 ref)</span>';
      else if (fms.composite_nlp === false && doc.reference_nlp) composite += " partial";
      var threads = cap.hardware_threads;
      if (hasNumeric(threads) && Number(threads) > 64) showCap = true;
      html += "<tr><td>" + esc(peerLabel(row)) + "</td><td>" + evidencePill(row, fms, doc) + "</td><td>" + composite + "</td><td>" +
        esc(scoreCell(fleet.fleet_mark)) + "</td>";
      STAGE_KEYS.forEach(function (pair) {
        var rate = doubleRate(row, pair[0]);
        html += "<td>" + (rate == null ? "Not measured" : esc(fmtStageRate(pair[0], rate))) + "</td>";
      });
      html += "<td>" + esc(cap.physical_cores != null ? cap.physical_cores : "—") + "</td><td>" +
        esc(cap.hardware_threads != null ? cap.hardware_threads : "—") + "</td></tr>";
    });
    html += "</tbody></table>";
    root.innerHTML = html;
    if (capNote) {
      if (showCap) {
        capNote.textContent =
          "Market Studio runner caps worker threads at 64 per stage. Hosts with more hardware threads run host-max-threads at the capped width, not at the full CPU count.";
        capNote.classList.remove("d-none");
      } else {
        capNote.classList.add("d-none");
      }
    }
  }

  function stageLevel(stage, width) {
    if (!stage || !stage[width]) return { rate: null, seconds: null };
    return stage[width];
  }

  function nlpBandwidth(name, level) {
    if (name !== "nlp" || !level || !hasNumeric(level.gib_per_second)) return "";
    return " · " + Number(level.gib_per_second).toFixed(1) + " GiB/s";
  }

  function renderStageGrid(doc) {
    var root = document.getElementById("fleet-bench-measure-body");
    if (!root) return;
    var rows = doc && doc.rows ? doc.rows : [];
    if (!rows.length) {
      root.textContent = "No measurements yet.";
      return;
    }
    var batch = doc && doc.batch;
    var html = "";
    if (batch && batch.targets && batch.targets.length) {
      var bits = batch.targets.map(function (target) {
        var label = target.label || target.peer_id;
        return label + " " + (target.status || "queued") + (target.error ? " (" + target.error + ")" : "");
      });
      html += "<p class=\"mb-2\">All-peer " + esc(batch.suite === "hardware" ? "hardware" : "Market Studio") +
        " · " + esc(batch.status || "") + ": " + esc(bits.join("; ")) + "</p>";
    }
    html += "<table class=\"table table-sm mb-3\"><thead><tr>" +
      "<th>Peer</th><th>Wall</th><th>Max cores</th><th>Max threads</th><th>Stress</th>" +
      "</tr></thead><tbody>";
    rows.forEach(function (row) {
      var fms = row.fmsbench || {};
      var stages = fms.stages || {};
      function widthCell(name, scoreKey) {
        var widths = fms.widths || {};
        var entry = widths[name] || {};
        if (fms[scoreKey] != null) return scoreCell(fms[scoreKey]) + (entry.threads != null ? " · " + entry.threads : "");
        if (entry.status) return entry.status + (entry.threads != null ? " · " + entry.threads : "");
        return "—";
      }
      var stressCell = fms.stress_score != null ? scoreCell(fms.stress_score) : (fms.stress_status || "—");
      if (fms.stress && fms.stress.threads) stressCell += " · " + fms.stress.threads + " threads";
      html += "<tr><td>" + esc(peerLabel(row)) + "</td><td>" +
        esc(fmtSeconds(stages.wall_seconds || fms.wall_seconds)) + "</td><td>" +
        esc(widthCell("host-max-cores", "cores_score")) + "</td><td>" +
        esc(widthCell("host-max-threads", "threads_score")) + "</td><td>" + esc(stressCell) + "</td></tr>";
    });
    html += "</tbody></table>";
    html += "<table class=\"table table-sm mb-0\"><thead><tr>" +
      "<th>Peer</th><th>Stage</th><th>1 thread</th><th>1 thread time</th><th>2 threads</th><th>2 thread time</th><th>Stage time</th>" +
      "</tr></thead><tbody>";
    var stageNames = [
      ["postgres", "PostgreSQL"],
      ["duckdb", "DuckDB"],
      ["sqlite", "SQLite"],
      ["compute", "Compute"],
      ["nlp", "NLP 1 GiB"],
    ];
    rows.forEach(function (row) {
      var fms = row.fmsbench || {};
      var who = peerLabel(row);
      var inner = fms.stages && fms.stages.stages ? fms.stages.stages : {};
      if (!fms.stages) {
        html += "<tr><td>" + esc(who) + "</td><td colspan=\"6\">" + esc(fms.status || "not_run") + "</td></tr>";
        return;
      }
      stageNames.forEach(function (pair) {
        var stage = inner[pair[0]] || {};
        var one = stageLevel(stage, "single");
        var two = stageLevel(stage, "double");
        html += "<tr><td>" + esc(who) + "</td><td>" + esc(pair[1]) + "</td><td>" +
          esc(fmtStageRate(pair[0], one.rate)) + esc(nlpBandwidth(pair[0], one)) + "</td><td>" + esc(fmtSeconds(one.seconds)) + "</td><td>" +
          esc(fmtStageRate(pair[0], two.rate)) + esc(nlpBandwidth(pair[0], two)) + "</td><td>" + esc(fmtSeconds(two.seconds)) + "</td><td>" +
          esc(fmtSeconds(stage.stage_seconds)) + "</td></tr>";
      });
    });
    html += "</tbody></table>";
    root.innerHTML = html;
  }

  function syncPageTitle() {
    var title = document.getElementById("fleet-bench-page-title");
    if (!title) return;
    try {
      var peer = (localStorage.getItem("forgeFleetActiveRemotePeer") || "").trim();
      if (peer) {
        var sel = document.getElementById("fleet-scope-select");
        var label = peer;
        if (sel && sel.value === peer && sel.options[sel.selectedIndex]) {
          label = (sel.options[sel.selectedIndex].textContent || peer).trim();
        }
        title.textContent = "Forge Benchmarks — " + label;
      } else {
        title.textContent = "Forge Benchmarks";
      }
    } catch (_e) {
      title.textContent = "Forge Benchmarks";
    }
  }

  function updateProfileHint() {
    var sel = document.getElementById("fleet-cap-fms-profile");
    var hint = document.getElementById("fleet-bench-profile-hint");
    if (!sel || !hint) return;
    var v = sel.value || "standard";
    hint.textContent = PROFILE_HINTS[v] || PROFILE_HINTS.standard;
  }

  function render(doc) {
    if (!doc || !doc.ok) return;
    syncPageTitle();
    renderAnswers(doc);
    renderWorkloads(doc);
    renderNodes(doc);
    renderStageGrid(doc);
  }

  function wireProfileHint() {
    var sel = document.getElementById("fleet-cap-fms-profile");
    if (sel) {
      sel.addEventListener("change", updateProfileHint);
      updateProfileHint();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireProfileHint);
  } else {
    wireProfileHint();
  }

  window.forgeFleetBenchmarksView = { render: render };
})();
