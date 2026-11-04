/* Fleet Performance Intelligence — prototype-fidelity studio (GET /v1/mesh/benchmarks/score). */
(function () {
  "use strict";

  var STAGES = ["postgresql", "duckdb", "sqlite", "numpy", "nlp"];
  var STAGE_META = {
    postgresql: { label: "PostgreSQL", short: "PG", color: "#457fee", interpret: "PostgreSQL throughput reflects query planning, connection overhead, and storage I/O in the synthetic bundle fixture." },
    duckdb: { label: "DuckDB", short: "Duck", color: "#10a68d", interpret: "DuckDB in-process analytics can scale well when worker count matches CPU and memory bandwidth." },
    sqlite: { label: "SQLite", short: "SQL", color: "#c99a56", interpret: "SQLite may be sensitive to write serialization, locking, and fixture design." },
    numpy: { label: "NumPy", short: "NumPy", color: "#7567be", interpret: "NumPy compute stages stress CPU vectorization and memory bandwidth." },
    nlp: { label: "NLP 1 GiB", short: "NLP", color: "#bc5262", interpret: "NLP stages mix tokenization and model inference; parallel gain varies with batch design." },
  };
  var NODE_PALETTE = ["#4d87f3", "#16a58d", "#c99a56", "#7567be", "#bc5262", "#e07b39", "#5b8cec"];
  var LS_BASELINE = "forgeFpiBaseline";
  var LS_SNAPSHOTS = "forgeFpiIncludeSnapshots";
  var LS_WEIGHTS = "forgeFpiWeights";
  var LS_PAGE = "forgeFpiPage";
  var LS_STAGE = "forgeFpiStage";
  var LS_NODE = "forgeFpiNode";
  var DEFAULT_W = "22,28,10,12,28";

  var PAGE_COPY = {
    overview: { title: "Performance command center", lead: "Multi-thread throughput, capacity scoring, and operational decisions." },
    threads: { title: "Multi-thread explorer", lead: "Compare single-worker and maximum-worker rates per workload." },
    scoring: { title: "Cluster scoring", lead: "Tune weights, baseline reference, and inspect score anatomy." },
    insights: { title: "Insights & recommended actions", lead: "Turn descriptive performance signals into testable engineering next steps." },
    evidence: { title: "Nodes & evidence", lead: "Measurement provenance, raw runs, and benchmark controls." },
  };

  var DOC = null;
  var ON_POLICY = null;
  var BOUND = false;
  var STATE = { page: "overview", stage: "postgresql", node: "local" };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function num(n, d) {
    if (n == null || n === "" || Number.isNaN(Number(n))) return "—";
    var x = Number(n);
    if (d == null) return String(Math.round(x * 10) / 10);
    return x.toFixed(d);
  }

  function fmtScore(n) {
    return num(n, 1);
  }

  function pill(text, color) {
    return '<span class="pill ' + esc(color) + '">' + esc(text) + "</span>";
  }

  function sevPill(sev) {
    if (sev === "blocker") return pill("HIGH", "red");
    if (sev === "attention") return pill("HIGH", "red");
    return pill("Medium", "blue");
  }

  function insightHeadline(item) {
    var obs = String(item.observation || "");
    var dot = obs.indexOf(".");
    if (dot > 20 && dot < 120) return obs.slice(0, dot + 1);
    if (obs.length > 100) return obs.slice(0, 97) + "…";
    return obs || item.rule_id || "Finding";
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

  function loadState() {
    try {
      var pg = localStorage.getItem(LS_PAGE);
      if (pg && PAGE_COPY[pg]) STATE.page = pg;
      var st = localStorage.getItem(LS_STAGE);
      if (st && STAGE_META[st]) STATE.stage = st;
      var nd = localStorage.getItem(LS_NODE);
      if (nd) STATE.node = nd;
    } catch (_e) {}
  }

  function saveState() {
    try {
      localStorage.setItem(LS_PAGE, STATE.page);
      localStorage.setItem(LS_STAGE, STATE.stage);
      localStorage.setItem(LS_NODE, STATE.node);
    } catch (_e) {}
  }

  function nodes(doc) {
    return (doc && doc.nodes) || [];
  }

  function nodeById(doc, id) {
    return nodes(doc).find(function (n) {
      return n.node_id === id;
    });
  }

  function included(doc) {
    return nodes(doc).filter(function (n) {
      return n.included_in_cluster;
    });
  }

  function nodeColor(doc, nodeId) {
    var list = nodes(doc);
    var baseId = (doc.baseline && doc.baseline.node_id) || "";
    var ordered = [];
    var seen = {};
    if (baseId) {
      var b = nodeById(doc, baseId);
      if (b) {
        ordered.push(b);
        seen[b.node_id] = true;
      }
    }
    list.forEach(function (n) {
      if (!seen[n.node_id]) ordered.push(n);
    });
    for (var i = 0; i < ordered.length; i++) {
      if (ordered[i].node_id === nodeId) return NODE_PALETTE[i % NODE_PALETTE.length];
    }
    return NODE_PALETTE[0];
  }

  function heroComposite(doc) {
    var cluster = doc.cluster || {};
    if (cluster.composite != null) return cluster.composite;
    return cluster.composite_confirmed;
  }

  function baselineReady(doc) {
    var b = doc.baseline || {};
    return b.status === "measured" || b.status === "temporary_fallback";
  }

  function measured(node) {
    return node && node.composite != null;
  }

  function heatColor(v) {
    if (v == null) return "#f3f5f9";
    if (v < 1.5) return "#faede7";
    if (v < 2.5) return "#fff0db";
    if (v < 4) return "#edf1ff";
    if (v < 5) return "#dfeafe";
    return "#ccdfef";
  }

  function formatRate(val, unit) {
    if (val == null) return "—";
    if (unit === "million_rows/s") return num(val, 1) + "M rows/s";
    if (unit === "docs/s") return num(val, 0) + " docs/s";
    return num(val, 2) + " " + (unit || "");
  }

  function scoreLabel(val, decimals) {
    if (val == null) return '<span class="placeholder">—</span>';
    return "<b>" + num(val, decimals == null ? 1 : decimals) + "</b>";
  }

  function evidencePill(ev, connectivity) {
    if (ev === "saved_snapshot") return pill("Saved · " + (connectivity || "snapshot"), "amber");
    if (ev === "not_run" || ev === "run_failed") return pill("Not run", "red");
    if (ev === "recorded") return pill("Stage rates recorded", "green");
    return pill(String(ev || "unknown"), "gray");
  }

  function benchNote(doc) {
    var baseline = doc.baseline || {};
    var policy = readPolicy(baseline.node_id || "local");
    var snapNodes = nodes(doc).filter(function (n) {
      return n.evidence === "saved_snapshot";
    });
    var snapTxt =
      snapNodes.length && policy.include_snapshots
        ? snapNodes.map(function (n) {
            return n.label;
          }).join(", ") + " saved snapshot(s) included."
        : snapNodes.length
          ? "Saved snapshots excluded from headline score."
          : "";
    var missing = nodes(doc).filter(function (n) {
      return n.composite == null;
    });
    var missTxt = missing.length
      ? missing.map(function (n) {
          return n.label;
        }).join(", ") + " lack workload rates."
      : "All known nodes have workload rates or are explicitly excluded.";
    return (
      '<div class="notice"><span class="notice-icon">ⓘ</span><div><b>Capacity model, not a distributed throughput test.</b> ' +
      "Cluster scores sum independent-node benchmark rates, normalized to <b>" +
      esc(baseline.label || baseline.node_id || "baseline") +
      "</b> and blended across workloads. Network, scheduling, and inter-node overhead are <b>not measured</b>. " +
      esc(snapTxt) +
      " " +
      esc(missTxt) +
      "</div></div>"
    );
  }

  function scoreStack(doc) {
    var inc = included(doc);
    var total = heroComposite(doc);
    if (total == null || !inc.length) {
      return '<div class="empty"><h3>Awaiting baseline</h3><p>Select a measured baseline host to compute modeled cluster capacity.</p></div>';
    }
    var sum = 0;
    inc.forEach(function (n) {
      sum += Number(n.composite) || 0;
    });
    if (sum <= 0) sum = total;
    var bars = inc
      .map(function (n) {
        var w = (100 * (Number(n.composite) || 0)) / sum;
        return (
          '<div class="segment" style="width:' +
          Math.max(w, 0.5) +
          "%;background:" +
          nodeColor(doc, n.node_id) +
          '" title="' +
          esc(n.label) +
          '"></div>'
        );
      })
      .join("");
    var labels = inc
      .map(function (n) {
        return (
          "<span><i class=\"legenddot\" style=\"background:" +
          nodeColor(doc, n.node_id) +
          '"></i>' +
          esc(n.label) +
          " <b>" +
          num(n.composite, 1) +
          "</b></span>"
        );
      })
      .join("");
    var cluster = doc.cluster || {};
    var alt =
      cluster.composite_with_snapshots != null &&
      cluster.composite_confirmed != null &&
      Math.abs(Number(cluster.composite_with_snapshots) - Number(cluster.composite_confirmed)) > 0.05
        ? '<div class="segmentlabels topgap">Including saved snapshots: <b>' +
          num(cluster.composite_with_snapshots, 1) +
          "</b> (headline uses " +
          (doc.include_snapshots ? "snapshot-inclusive" : "confirmed-live") +
          " policy)</div>"
        : "";
    return '<div class="contribs"><div class="segmentbar">' + bars + '</div><div class="segmentlabels">' + labels + "</div>" + alt + "</div>";
  }

  function hero(doc) {
    var composite = heroComposite(doc);
    var baseline = doc.baseline || {};
    var inc = included(doc);
    var mult = composite != null ? num(composite / 100, 2) : "—";
    return (
      '<div class="hero"><section id="fleet-perf-hero" class="heroscore"><div class="herolabel">MODELED CLUSTER CAPACITY SCORE</div><div class="heroline"><div class="heroval">' +
      (composite == null ? "—" : num(composite, 1)) +
      "</div>" +
      (composite == null ? "" : '<div class="heroex">' + mult + "× reference</div>") +
      '</div><div class="herocopy">' +
      (baselineReady(doc)
        ? "Baseline: " +
          esc(baseline.label || baseline.node_id) +
          " = 100. All " +
          inc.length +
          " included nodes combined through weighted workload throughput."
        : "Choose a baseline with complete standard-profile stage rates to compute cluster capacity.") +
      "</div>" +
      scoreStack(doc) +
      '</section><section class="card herosecond"><div><div class="kicker">What does this number mean?</div><h3>Capacity ≠ parallel efficiency</h3></div><div class="meaningline"><div class="meaningico">Σ</div><div><strong>Overall throughput potential</strong><p>The index measures aggregate standalone processing capacity across measured workloads. 200 points means twice the reference modeled workload capacity.</p></div></div><div class="meaningline"><div class="meaningico">↗</div><div><strong>Multi-thread performance</strong><p>Speedup compares maximum-worker throughput with one-worker throughput. It is displayed separately from cluster capacity.</p></div></div><button type="button" class="textlink" data-page="scoring">Inspect score formula &amp; weights →</button></section></div>'
    );
  }

  function kpis(doc) {
    var comps = doc.components || {};
    var ranked = STAGES.map(function (sid) {
      return { sid: sid, v: (comps[sid] || {}).cluster_index };
    })
      .filter(function (x) {
        return x.v != null;
      })
      .sort(function (a, b) {
        return b.v - a.v;
      });
    var best = ranked[0];
    var worst = ranked[ranked.length - 1];
    var baseId = (doc.baseline && doc.baseline.node_id) || STATE.node;
    var baseNode = nodeById(doc, baseId) || nodes(doc)[0];
    var peak = { sid: "duckdb", speedup: 0 };
    STAGES.forEach(function (sid) {
      var c = baseNode && (baseNode.components || {})[sid];
      if (c && c.speedup != null && c.speedup >= peak.speedup) {
        peak = { sid: sid, speedup: c.speedup, workers: c.max_workers };
      }
    });
    var meta = STAGE_META[peak.sid] || { label: peak.sid };
    var total = nodes(doc).length;
    var withRates = nodes(doc).filter(function (n) {
      return n.composite != null;
    }).length;
    var snapOnly = nodes(doc).filter(function (n) {
      return n.evidence === "saved_snapshot";
    }).length;
    return (
      '<div class="kpis"><button type="button" class="card kpi" data-page="scoring"><div class="klabel">Best workload capacity</div><div class="kvalue kc">' +
      (best ? num(best.v, 0) : "—") +
      '</div><div class="kdetail">' +
      (best ? STAGE_META[best.sid].label : "Awaiting baseline") +
      " · total vs reference</div></button>" +
      '<button type="button" class="card kpi" data-page="scoring"><div class="klabel">Capacity bottleneck</div><div class="kvalue">' +
      (worst ? num(worst.v, 0) : "—") +
      '</div><div class="kdetail">' +
      (worst ? STAGE_META[worst.sid].label : "Awaiting baseline") +
      " · weakest index</div></button>" +
      '<button type="button" class="card kpi" data-action="openStage" data-id="' +
      esc(peak.sid) +
      '"><div class="klabel">Best baseline scaling</div><div class="kvalue">' +
      num(peak.speedup, 2) +
      "×</div><div class=\"kdetail\">" +
      esc(meta.label) +
      " · 1 → " +
      (peak.workers || "?") +
      " workers</div></button>" +
      '<button type="button" class="card kpi" data-page="evidence"><div class="klabel">Measured node coverage</div><div class="kvalue">' +
      withRates +
      ' <small style="font-size:15px;color:#9ca7b5">/ ' +
      total +
      "</small></div><div class=\"kdetail\">" +
      (total - withRates > 0 ? total - withRates + " missing run" : "All nodes measured") +
      (snapOnly ? " · " + snapOnly + " snapshot" : "") +
      "</div></button></div>"
    );
  }

  function metricCards(doc) {
    var comps = doc.components || {};
    var wPct = doc.weights_display_percent || {};
    return (
      '<section class="card pad"><div class="rowbetween"><div><div class="sectiontitle">Component scores</div><div class="sectiondesc">Cluster capacity by workload · baseline 100 for each component</div></div><button type="button" class="textlink" data-page="scoring">Customize composite weights →</button></div><div class="metricgrid">' +
      STAGES.map(function (sid) {
        var c = comps[sid] || {};
        var v = c.cluster_index;
        var meta = STAGE_META[sid];
        var wt = wPct[sid] != null ? wPct[sid] : Math.round((c.weight || 0) * 100);
        return (
          '<button type="button" class="metriccard" data-action="openStage" data-id="' +
          sid +
          '"><div class="metricname">' +
          esc(meta.label) +
          '</div><div class="metricweight">' +
          num(wt, 1) +
          '% weight</div><div class="metricnum">' +
          (v == null ? "—" : num(v, 0)) +
          ' <small>/ 100</small></div><div class="smalltrack"><span style="width:' +
          (v == null ? 0 : Math.min((v / 225) * 100, 100)) +
          "%;background:" +
          meta.color +
          '"></span></div><div class="metricminor">' +
          (v == null ? "Needs baseline" : num(v / 100, 2) + "× reference capacity") +
          "</div></button>"
        );
      }).join("") +
      "</div></section>"
    );
  }

  function heatmap(doc) {
    var rows = nodes(doc);
    return (
      '<section class="card pad"><div class="rowbetween"><div><div class="sectiontitle">Multi-thread scaling matrix</div><div class="sectiondesc">Actual throughput speedup: max-worker rate ÷ 1-worker rate</div></div><button type="button" class="textlink" data-page="threads">Explore rates →</button></div><div class="heatwrap"><table class="heat"><thead><tr><th>Node</th>' +
      STAGES.map(function (sid) {
        return "<th>" + STAGE_META[sid].short + "</th>";
      }).join("") +
      '</tr></thead><tbody>' +
      rows
        .map(function (n) {
          var note = "recorded";
          if (n.evidence === "saved_snapshot") note = "snapshot";
          else if (n.composite == null) note = "no data";
          else if (n.worker_oversubscription) note = (n.components && n.components.postgresql && n.components.postgresql.max_workers) + " workers / " + (n.logical_cpus || "?") + " logical";
          return (
            "<tr><td><div class=\"heatnode\">" +
            esc(n.label) +
            '</div><div class="heatnote">' +
            esc(note) +
            "</div></td>" +
            STAGES.map(function (sid) {
              var c = (n.components || {})[sid] || {};
              var v = c.speedup;
              var sub = v == null ? "no run" : c.max_workers == null ? "workers unknown" : c.max_workers + " workers";
              return (
                '<td><button type="button" ' +
                (v == null ? "disabled" : "") +
                ' data-action="openStage" data-id="' +
                sid +
                '" class="heatbutton ' +
                (v == null ? "na" : "") +
                '" style="background:' +
                heatColor(v) +
                '"><strong>' +
                (v == null ? "—" : num(v, 2) + "×") +
                "</strong><span>" +
                esc(sub) +
                "</span></button></td>"
              );
            }).join("") +
            "</tr>"
          );
        })
        .join("") +
      '</tbody></table></div><div class="foot">A speedup of 5× means the maximum-worker run processes ~5× as much per second as one worker. It does not imply 5× per-core efficiency.</div></section>'
    );
  }

  function overviewInsights(doc) {
    var list = doc.insights || [];
    var high = list.filter(function (i) {
      return i.severity === "blocker" || i.severity === "attention";
    }).length;
    var top = list.slice(0, 3);
    return (
      '<aside class="card pad"><div class="rowbetween"><div><div class="sectiontitle">Decision signals</div><div class="sectiondesc">Description → meaning → next action</div></div>' +
      pill(String(high || top.length) + " priority", "amber") +
      "</div>" +
      (top.length
        ? top
            .map(function (item) {
              return (
                '<div class="insightitem"><div class="head">' +
                sevPill(item.severity) +
                " " +
                esc(insightHeadline(item)) +
                '</div><p>' +
                esc(item.meaning) +
                '</p><button type="button" class="smallaction" data-page="insights">' +
                esc(item.recommended_action || "View") +
                " →</button></div>"
              );
            })
            .join("")
        : '<p class="sectiondesc">No priority findings.</p>') +
      "</aside>"
    );
  }

  function workloadScoreTable(doc) {
    var comps = doc.components || {};
    var inc = included(doc);
    return (
      '<section class="card pad sectionblock"><div class="rowbetween"><div><div class="sectiontitle">Where the cluster score comes from</div><div class="sectiondesc">Component indexes and weighted contributions for included nodes</div></div><button type="button" class="textlink" data-page="scoring">Full score anatomy →</button></div><div class="tablewrap"><table class="table"><thead><tr><th>Component</th><th>Weight</th><th>Aggregated raw rate</th><th>Capacity index</th><th>Contribution</th><th></th></tr></thead><tbody>' +
      STAGES.map(function (sid) {
        var c = comps[sid] || {};
        var meta = STAGE_META[sid];
        var agg = 0;
        inc.forEach(function (n) {
          var st = (n.components || {})[sid];
          if (st && st.max_rate != null) agg += Number(st.max_rate);
        });
        return (
          "<tr><td><b>" +
          esc(meta.label) +
          "</b></td><td>" +
          num((c.weight || 0) * 100, 1) +
          "%</td><td>" +
          formatRate(agg, c.unit) +
          "</td><td>" +
          scoreLabel(c.cluster_index) +
          "</td><td>" +
          num(c.weighted_contribution, 1) +
          ' pts</td><td><button type="button" class="textlink" data-action="openStage" data-id="' +
          sid +
          '">View ›</button></td></tr>'
        );
      }).join("") +
      "</tbody></table></div></section>"
    );
  }

  function pageOverview(doc) {
    return benchNote(doc) + hero(doc) + kpis(doc) + metricCards(doc) + '<div class="overviewcols">' + heatmap(doc) + overviewInsights(doc) + "</div>" + workloadScoreTable(doc);
  }

  function stageTabs() {
    return (
      '<div class="tabrow">' +
      STAGES.map(function (sid) {
        return (
          '<button type="button" class="tabchip ' +
          (STATE.stage === sid ? "active" : "") +
          '" data-action="pickStage" data-id="' +
          sid +
          '">' +
          STAGE_META[sid].label +
          "</button>"
        );
      }).join("") +
      "</div>"
    );
  }

  function throughputCard(doc, n, sid) {
    var meta = STAGE_META[sid];
    var c = (n.components || {})[sid] || {};
    if (n.composite == null) {
      return (
        '<div class="comparecard"><div class="comparename">' +
        esc(n.label) +
        " " +
        pill("Not measured", "gray") +
        '</div><div class="comparesub">No 1-worker or multi-worker rates recorded for this node.</div><button type="button" class="textlink topgap" data-action="planRun">Plan retry →</button></div>'
      );
    }
    var maxRate = 0;
    nodes(doc).forEach(function (z) {
      var x = (z.components || {})[sid];
      if (x && x.max_rate != null && x.max_rate > maxRate) maxRate = x.max_rate;
    });
    var sp = c.speedup;
    var workers = c.max_workers;
    var eff = c.worker_efficiency != null ? num(c.worker_efficiency * 100, 0) + "%" : "—";
    return (
      '<div class="comparecard ' +
      (STATE.node === n.node_id ? "selected" : "") +
      '" data-action="pickNode" data-id="' +
      esc(n.node_id) +
      '"><div class="comparetops"><div><div class="comparename">' +
      esc(n.label) +
      " " +
      (n.evidence === "saved_snapshot" ? pill("Snapshot", "amber") : "") +
      '</div><div class="comparesub">' +
      (n.physical_cores != null ? n.physical_cores + " physical" : "—") +
      " / " +
      (n.logical_cpus != null ? n.logical_cpus + " logical" : "—") +
      " CPU threads · " +
      (workers == null ? "worker count not captured" : workers + " benchmark workers") +
      (n.worker_oversubscription ? " · oversubscribed" : "") +
      '</div></div><div class="gainbox"><div><div class="biggain">' +
      num(sp, 2) +
      '×</div><div class="hint">1 → max speedup</div></div><div><div class="biggain" style="color:var(--fpi-blue)">' +
      scoreLabel(c.index, 0) +
      '</div><div class="hint">component score</div></div></div></div><div class="dualbars"><div class="dualbarrow"><span>1 worker</span><div class="track"><div class="fill" style="width:' +
      Math.max(1, maxRate ? (c.single_rate / maxRate) * 100 : 0) +
      '%"></div></div><b>' +
      formatRate(c.single_rate, c.unit) +
      '</b></div><div class="dualbarrow"><span>Max workers</span><div class="track"><div class="fill multi" style="width:' +
      Math.max(1, maxRate ? (c.max_rate / maxRate) * 100 : 0) +
      "%;background:" +
      nodeColor(doc, n.node_id) +
      '"></div></div><b>' +
      formatRate(c.max_rate, c.unit) +
      '</b></div></div><div class="foot">' +
      (workers ? "Worker efficiency vs ideal: " + eff : "Efficiency unavailable: worker count not captured.") +
      "</div></div>"
    );
  }

  function throughputSidebar(doc, sid) {
    var meta = STAGE_META[sid];
    var baseId = (doc.baseline && doc.baseline.node_id) || "";
    var p = nodeById(doc, baseId);
    var others = nodes(doc).filter(function (n) {
      return n.node_id !== baseId && measured(n);
    });
    var m = others[0];
    var stageInsights = (doc.insights_all || doc.insights || []).filter(function (i) {
      return i.scope && i.scope.workload === sid;
    });
    var inv =
      stageInsights.length > 0
        ? "<p class=\"sectiondesc topgap\">" + esc(stageInsights[0].observation) + "</p><p class=\"sectiondesc\"><b>Next:</b> " + esc(stageInsights[0].recommended_action) + "</p>"
        : "<p class=\"sectiondesc topgap\">Run a worker sweep with identical fixture size and capture stage breakdown.</p>";
    return (
      '<div class="card pad"><div class="sectiontitle">What ' +
      esc(meta.label) +
      ' tells us</div><div class="sectiondesc">Compare single-worker rate, maximum-worker rate, speedup, and baseline component score.</div><div class="scalegrid"><div class="scalestat"><div class="label">Baseline scaling</div><b>' +
      num(p && (p.components || {})[sid] && (p.components || {})[sid].speedup, 2) +
      "×</b></div><div class=\"scalestat\"><div class=\"label\">Peer scaling</div><b>" +
      num(m && (m.components || {})[sid] && (m.components || {})[sid].speedup, 2) +
      '×</b></div></div><div class="definition"><b>Read it as:</b> ' +
      esc(meta.interpret) +
      " The score compares maximum-worker rate to the chosen baseline; speedup compares to the same node's own 1-worker rate.</div><hr class=\"sep\"><div class=\"sectiontitle\" style=\"font-size:13px\">What to investigate</div>" +
      inv +
      "</div>"
    );
  }

  function multiSummary(doc) {
    return (
      '<section class="card pad sectionblock"><div class="rowbetween"><div><div class="sectiontitle">Multi-thread gain across all workloads</div><div class="sectiondesc">Speedup is an intra-node ratio; it is independent of baseline selection.</div></div></div><div class="workgrid topgap">' +
      nodes(doc)
        .filter(measured)
        .map(function (n) {
          return (
            '<div class="workerbox"><h4>' +
            esc(n.label) +
            " " +
            (n.worker_oversubscription ? pill("oversubscribed", "amber") : pill("measured", "blue")) +
            "</h4>" +
            STAGES.map(function (sid) {
              var c = (n.components || {})[sid] || {};
              return (
                '<div class="workrow"><span>' +
                STAGE_META[sid].short +
                '</span><div class="bar"><span style="width:' +
                Math.min(((c.speedup || 0) / 8) * 100, 100) +
                "%;background:" +
                nodeColor(doc, n.node_id) +
                '"></span></div><b>' +
                num(c.speedup, 2) +
                "×</b></div>"
              );
            }).join("") +
            "</div>"
          );
        })
        .join("") +
      '</div><div class="foot">Bar scale: 8× speedup. These rates do not establish how many physical cores or CPU threads were utilized.</div></section>'
    );
  }

  function pageThreads(doc) {
    var sid = STATE.stage;
    return (
      benchNote(doc) +
      '<section class="card pad"><div class="rowbetween"><div><div class="sectiontitle">Workload throughput &amp; scaling</div><div class="sectiondesc">Compare single-worker rate, maximum-worker rate, speedup, and baseline component score.</div></div>' +
      pill("Max-worker rates from Fleet runs", "blue") +
      "</div>" +
      stageTabs() +
      '<div class="two"><div>' +
      nodes(doc)
        .map(function (n) {
          return throughputCard(doc, n, sid);
        })
        .join("") +
      "</div>" +
      throughputSidebar(doc, sid) +
      "</div></section>" +
      multiSummary(doc)
    );
  }

  function weightEditors(doc) {
    var wPct = doc.weights_display_percent || {};
    var policy = readPolicy((doc.baseline && doc.baseline.node_id) || "local");
    var raw = (policy.weights || DEFAULT_W).split(",");
    return STAGES.map(function (sid, i) {
      var val = raw[i] != null ? raw[i] : Math.round(wPct[sid] || 0);
      return (
        '<div class="weightrow"><label for="weight_' +
        sid +
        '">' +
        STAGE_META[sid].label +
        '</label><input type="range" min="0" max="60" step="1" value="' +
        esc(String(val)) +
        '" id="weight_' +
        sid +
        '" data-weight="' +
        sid +
        '" aria-label="' +
        esc(STAGE_META[sid].label) +
        ' weight"><output id="out_' +
        sid +
        '">' +
        num(wPct[sid], 1) +
        "%</output></div>"
      );
    }).join("");
  }

  function scoreFormula() {
    return '<div class="equation">StageIndexₛ = 100 × node max-worker throughputₛ / reference throughputₛ<br>NodeCompositeₙ = Σ(weightₛ × StageIndexₙ,ₛ)<br>ClusterComposite = Σ(included NodeCompositeₙ)<br>Component cluster index = Σ(included node stage indexes) per workload</div>';
  }

  function scoreMatrix(doc) {
    var baseline = doc.baseline || {};
    var comps = doc.components || {};
    return (
      '<section class="card pad sectionblock"><div class="rowbetween"><div><div class="sectiontitle">Score anatomy · each workload and node</div><div class="sectiondesc">Individual component scores and total share the same reference. No node is capped at 100.</div></div>' +
      pill("Reference: " + (baseline.label || baseline.node_id) + " = 100", "blue") +
      '</div><div class="tablewrap"><table class="table"><thead><tr><th>System</th>' +
      STAGES.map(function (sid) {
        return "<th>" + STAGE_META[sid].label + "<br><span style=\"font-weight:500\">" + num((comps[sid] || {}).weight * 100, 1) + "% weight</span></th>";
      }).join("") +
      '<th>Composite</th></tr></thead><tbody>' +
      nodes(doc)
        .map(function (n) {
          return (
            '<tr class="click" data-action="openNode" data-id="' +
            esc(n.node_id) +
            '"><td><b>' +
            esc(n.label) +
            "</b> " +
            (n.evidence === "saved_snapshot" ? pill("saved", "amber") : n.composite == null ? pill("missing", "gray") : "") +
            "</td>" +
            STAGES.map(function (sid) {
              var c = (n.components || {})[sid] || {};
              return "<td>" + scoreLabel(c.index) + "</td>";
            }).join("") +
            "<td><b>" +
            scoreLabel(n.composite) +
            "</b></td></tr>"
          );
        })
        .join("") +
      '<tr style="background:#f0f6ff"><td><b>CLUSTER · included</b></td>' +
      STAGES.map(function (sid) {
        return "<td><b>" + scoreLabel((comps[sid] || {}).cluster_index) + "</b></td>";
      }).join("") +
      '<td><b style="font-size:17px;color:#306ee6">' +
      scoreLabel(heroComposite(doc)) +
      "</b></td></tr></tbody></table></div><div class=\"foot\">Nodes with unknown workload rates are omitted from cluster totals. Component index 100 means throughput equals the selected reference stage rate.</div></section>"
    );
  }

  function pageScoring(doc) {
    var policy = readPolicy((doc.baseline && doc.baseline.node_id) || "local");
    var snapNodes = nodes(doc)
      .filter(function (n) {
        return n.evidence === "saved_snapshot";
      })
      .map(function (n) {
        return n.label;
      })
      .join(", ");
    return (
      benchNote(doc) +
      '<div class="scoringhero"><div><div class="kicker">Cluster composite index</div><div class="scorelarge">' +
      scoreLabel(heroComposite(doc), 1) +
      '</div></div><div class="desc"><b>' +
      esc((doc.baseline && doc.baseline.label) || "Baseline") +
      ' = 100</b> · Weighted arithmetic blend of five independent stage capacity indexes. This is additive across included nodes and can exceed 100.</div></div><div class="two sectionblock"><section class="card pad"><div class="rowbetween"><div><div class="sectiontitle">Tune score weights</div><div class="sectiondesc">Release a slider to update the composite; weights normalize to 100%.</div></div><button type="button" class="btn small" data-action="resetWeights">Reset to source weights</button></div><div class="weights topgap" id="fleet-fpi-weight-sliders">' +
      weightEditors(doc) +
      '</div><hr class="sep"><label style="display:flex;gap:10px;align-items:center;cursor:pointer"><input type="checkbox" id="fleet-fpi-snapshots" ' +
      (policy.include_snapshots ? "checked" : "") +
      '><span><b>Include saved snapshots in headline score</b><span class="sectiondesc" style="display:block">' +
      (snapNodes ? esc(snapNodes) : "No snapshot-only nodes in this cluster.") +
      '</span></span></label></section><aside class="card pad"><div class="sectiontitle">How the index works</div><div class="sectiondesc">Explicit calculation, not a black-box hardware score</div><div class="topgap">' +
      scoreFormula() +
      '</div><div class="facts topgap"><div class="fact"><h4>Reference 100</h4><p>Each workload is normalized to the selected baseline host observed multi-worker result.</p></div><div class="fact"><h4>Capacity is additive</h4><p>Combining measured nodes yields summed modeled capacity before orchestration costs.</p></div><div class="fact"><h4>Not the hardware mark</h4><p>Hardware scores are a different synthetic test and are not folded into the workload composite.</p></div></div></aside></div>' +
      scoreMatrix(doc)
    );
  }

  function insightCards(doc) {
    var list = doc.insights_all || doc.insights || [];
    return (
      '<div class="insightgrid">' +
      list
        .map(function (item, i) {
          return (
            '<section class="card insightcard"><div class="rowbetween">' +
            sevPill(item.severity) +
            '<span class="hint">Finding ' +
            String(i + 1).padStart(2, "0") +
            "</span></div><h3>" +
            esc(insightHeadline(item)) +
            '</h3><div class="kicker" style="margin:0 0 5px">Observation</div><p>' +
            esc(item.observation) +
            '</p><div class="kicker" style="margin:0 0 5px">What it means</div><p>' +
            esc(item.meaning) +
            '</p><div class="prescript"><b>Recommended action</b><p style="margin-top:6px">' +
            esc(item.recommended_action) +
            '</p><button type="button" class="textlink" data-action="insightAct" data-rule="' +
            esc(item.rule_id) +
            '">' +
            esc(item.recommended_action || "Act") +
            " →</button></div></section>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  function pageInsights(doc) {
    var list = doc.insights_all || doc.insights || [];
    var high = list.filter(function (i) {
      return i.severity === "blocker" || i.severity === "attention";
    }).length;
    return (
      benchNote(doc) +
      '<section class="card pad" style="margin-bottom:14px"><div class="rowbetween"><div><div class="sectiontitle">From benchmark numbers to engineering decisions</div><div class="sectiondesc">Each finding explicitly separates observed evidence, interpretation, and recommended intervention.</div></div><div>' +
      pill(list.length + " findings", "blue") +
      " " +
      pill(high + " high priority", "amber") +
      "</div></div></section>" +
      insightCards(doc) +
      '<section class="card pad sectionblock"><div class="rowbetween"><div><div class="sectiontitle">Validation experiment</div><div class="sectiondesc">Suggested exit criteria before promoting this index to a production cluster KPI</div></div><button type="button" class="btn blue small" data-action="planRun">Plan validation →</button></div><div class="facts topgap"><div class="fact"><h4>1 · Capture a Granite reference</h4><p>Same benchmark fixture, same profile hash, same worker cap policy; five maximum-worker stage results.</p></div><div class="fact"><h4>2 · Correct worker metadata</h4><p>Report configured workers, effective workers, physical cores, logical threads, and actual utilization for every stage on every node.</p></div><div class="fact"><h4>3 · Verify distributed cluster scale-out</h4><p>Compare real simultaneous cross-node throughput against the additive model; make achieved efficiency an independent KPI.</p></div></div></section>'
    );
  }

  function nodeTabs(doc) {
    return (
      '<div class="nodeselect">' +
      nodes(doc)
        .map(function (n) {
          return (
            '<button type="button" class="' +
            (STATE.node === n.node_id ? "active" : "") +
            '" data-action="pickNode" data-id="' +
            esc(n.node_id) +
            '">' +
            esc(n.label) +
            "</button>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  function pageEvidence(doc) {
    var n = nodeById(doc, STATE.node) || nodes(doc)[0];
    if (!n) {
      return benchNote(doc) + '<div id="fleet-perf-evidence-slot"></div>';
    }
    var body =
      benchNote(doc) +
      '<section class="card pad"><div class="rowbetween"><div><div class="sectiontitle">Node inventory &amp; measurement provenance</div><div class="sectiondesc">No conflation of hardware mark, workload score, or observed multi-worker throughput.</div></div>' +
      pill(
        nodes(doc).filter(measured).length + " / " + nodes(doc).length + " measured",
        "blue"
      ) +
      "</div>" +
      nodeTabs(doc) +
      '<div class="rowbetween"><div><div class="sectiontitle" style="font-size:20px">' +
      esc(n.label) +
      '</div><div class="sectiondesc">Evidence: ' +
      esc(n.evidence) +
      (n.connectivity ? " · " + esc(n.connectivity) : "") +
      "</div></div>" +
      evidencePill(n.evidence, n.connectivity) +
      '</div><div class="nodestats"><div class="nodestat"><div class="name">Node composite</div><div class="value">' +
      scoreLabel(n.composite, 1) +
      '</div></div><div class="nodestat"><div class="name">Hardware score (separate)</div><div class="value">' +
      num(n.hardware_score, 0) +
      '</div></div><div class="nodestat"><div class="name">Physical cores</div><div class="value">' +
      (n.physical_cores != null ? n.physical_cores : "—") +
      '</div></div><div class="nodestat"><div class="name">Logical CPU threads</div><div class="value">' +
      (n.logical_cpus != null ? n.logical_cpus : "—") +
      "</div></div></div>";

    if (measured(n)) {
      body +=
        '<div class="tablewrap"><table class="table"><thead><tr><th>Workload</th><th>1 worker</th><th>Max workers</th><th>Speedup</th><th>Workers recorded</th><th>Component index</th><th>Composite pts</th></tr></thead><tbody>' +
        STAGES.map(function (sid) {
          var c = (n.components || {})[sid] || {};
          var w = (doc.components || {})[sid] || {};
          var pts = c.index != null && w.weight != null ? c.index * w.weight : null;
          return (
            '<tr class="click" data-action="openStage" data-id="' +
            sid +
            '"><td><b>' +
            STAGE_META[sid].label +
            "</b></td><td>" +
            formatRate(c.single_rate, c.unit) +
            "</td><td>" +
            formatRate(c.max_rate, c.unit) +
            "</td><td>" +
            num(c.speedup, 2) +
            "×</td><td>" +
            (c.max_workers != null ? c.max_workers : "Not captured") +
            "</td><td>" +
            scoreLabel(c.index) +
            "</td><td>" +
            scoreLabel(pts) +
            "</td></tr>"
          );
        }).join("") +
        "</tbody></table></div>";
    } else {
      body +=
        '<div class="empty"><h3>Unmeasured workload rates</h3><p>Hardware score alone cannot estimate SQL, NumPy, or NLP throughput. No component index or composite was inferred.</p><button type="button" class="btn blue small" data-action="planRun" data-id="' + esc(n.node_id) + '">Run on this host</button></div>';
    }
    if (n.worker_oversubscription) {
      body += '<div class="callout"><b>Worker mismatch:</b> reported benchmark workers exceed logical CPU threads. Flag oversubscription before interpreting parallel efficiency.</div>';
    }
    if (n.evidence === "saved_snapshot") {
      body += '<div class="callout"><b>Snapshot-only evidence:</b> live peer returned an error; snapshot may still be included in modeled capacity when enabled.</div>';
    }
    body += "</section>";
    return body;
  }

  function syncRunHostSelect() {
    var runSel = document.getElementById("fleet-bench-run-host");
    var scope = document.getElementById("fleet-scope-select");
    if (!runSel || !scope) return;
    var html = "";
    for (var i = 0; i < scope.options.length; i++) {
      var opt = scope.options[i];
      html += '<option value="' + esc(opt.value) + '">' + esc(opt.textContent || opt.value || "This console") + "</option>";
    }
    if (!html) html = '<option value="">This console</option>';
    if (runSel.getAttribute("data-opts") !== html) {
      runSel.innerHTML = html;
      runSel.setAttribute("data-opts", html);
    }
    var want = scope.value || "";
    var found = false;
    for (var j = 0; j < runSel.options.length; j++) {
      if (runSel.options[j].value === want) found = true;
    }
    runSel.value = found ? want : runSel.options[0] ? runSel.options[0].value : "";
  }

  function bindRunHostSelect() {
    var runSel = document.getElementById("fleet-bench-run-host");
    var scope = document.getElementById("fleet-scope-select");
    if (runSel && !runSel.getAttribute("data-bound")) {
      runSel.setAttribute("data-bound", "1");
      runSel.addEventListener("change", function () {
        var scopeEl = document.getElementById("fleet-scope-select");
        if (!scopeEl || scopeEl.value === runSel.value) return;
        scopeEl.value = runSel.value;
        scopeEl.dispatchEvent(new Event("change", { bubbles: true }));
      });
    }
    if (scope && !scope.getAttribute("data-fpi-host-sync")) {
      scope.setAttribute("data-fpi-host-sync", "1");
      scope.addEventListener("change", syncRunHostSelect);
    }
  }

  function showRunPanel(scroll) {
    var box = document.getElementById("fleet-perf-evidence-static");
    if (!box) return;
    var on = STATE.page === "evidence";
    box.classList.toggle("d-none", !on);
    if (on) {
      box.removeAttribute("aria-hidden");
      syncRunHostSelect();
      bindRunHostSelect();
      if (scroll) box.scrollIntoView({ block: "start", behavior: "smooth" });
    } else {
      box.setAttribute("aria-hidden", "true");
    }
  }

  function setRunHost(nodeId) {
    var scope = document.getElementById("fleet-scope-select");
    if (!scope || !nodeId) return false;
    var match = "";
    for (var i = 0; i < scope.options.length; i++) {
      var opt = scope.options[i];
      if (opt.value === nodeId || (opt.textContent || "").indexOf(nodeId) !== -1) {
        match = opt.value;
        break;
      }
    }
    if (!match && nodeId !== "local") return false;
    scope.value = match;
    scope.dispatchEvent(new Event("change", { bubbles: true }));
    syncRunHostSelect();
    return true;
  }

  function paintMain(doc) {
    var main = document.getElementById("fleet-perf-main");
    if (!main || !doc) return;
    var html = "";
    if (STATE.page === "overview") html = pageOverview(doc);
    else if (STATE.page === "threads") html = pageThreads(doc);
    else if (STATE.page === "scoring") html = pageScoring(doc);
    else if (STATE.page === "insights") html = pageInsights(doc);
    else if (STATE.page === "evidence") html = pageEvidence(doc);
    main.innerHTML = html;
    showRunPanel(false);
    bindWeightSliders(doc);
  }

  function bindWeightSliders(doc) {
    var box = document.getElementById("fleet-fpi-weight-sliders");
    if (!box || !ON_POLICY) return;
    var timer = null;
    function applyWeights() {
      var parts = [];
      STAGES.forEach(function (sid) {
        var inp = document.getElementById("weight_" + sid);
        parts.push(inp ? inp.value : "0");
      });
      var baseSel = document.getElementById("fleet-fpi-baseline");
      var snap = document.getElementById("fleet-fpi-snapshots");
      writePolicy({
        baseline: baseSel && baseSel.value ? baseSel.value : (doc.baseline && doc.baseline.node_id) || "local",
        include_snapshots: !!(snap && snap.checked),
        weights: parts.join(","),
      });
      ON_POLICY();
    }
    box.querySelectorAll('input[type="range"]').forEach(function (inp) {
      inp.oninput = function () {
        var sid = inp.getAttribute("data-weight");
        var out = document.getElementById("out_" + sid);
        if (out) out.textContent = inp.value + "% (normalized on apply)";
        clearTimeout(timer);
        timer = setTimeout(applyWeights, 400);
      };
    });
    var snap = document.getElementById("fleet-fpi-snapshots");
    if (snap) snap.onchange = applyWeights;
  }

  function updateBaselineSelect(doc) {
    var sel = document.getElementById("fleet-fpi-baseline");
    if (!sel) return;
    var policy = readPolicy((doc.baseline && doc.baseline.node_id) || "local");
    var opts = nodes(doc)
      .filter(function (n) {
        return n.composite != null;
      })
      .map(function (n) {
        return (
          '<option value="' +
          esc(n.node_id) +
          '"' +
          (n.node_id === policy.baseline ? " selected" : "") +
          ">" +
          esc(n.label) +
          "</option>"
        );
      })
      .join("");
    sel.innerHTML = opts || '<option value="local">local</option>';
    sel.onchange = function () {
      writePolicy({
        baseline: sel.value,
        include_snapshots: readPolicy().include_snapshots,
        weights: readPolicy().weights,
      });
      if (ON_POLICY) ON_POLICY();
    };
  }

  function updateConnectionBox(doc) {
    var box = document.getElementById("fleet-perf-connection");
    if (!box) return;
    var total = nodes(doc).length;
    var measuredCount = nodes(doc).filter(measured).length;
    var baseline = doc.baseline || {};
    box.innerHTML =
      '<b><span class="minidot"></span> Cluster view</b><br>' +
      total +
      " known nodes · " +
      measuredCount +
      " with workload results<br>Baseline: " +
      esc(baseline.label || baseline.node_id || "—");
  }

  function updateInsightsBadge(doc) {
    var badge = document.getElementById("fleet-perf-insights-badge");
    if (!badge) return;
    var n = (doc.insights_all || doc.insights || []).length;
    badge.textContent = String(n);
    badge.style.display = n ? "" : "none";
  }

  function syncPageChrome() {
    var copy = PAGE_COPY[STATE.page] || PAGE_COPY.overview;
    var title = document.getElementById("fleet-perf-title");
    var sub = document.getElementById("fleet-perf-subtitle");
    if (title) title.textContent = copy.title;
    if (sub) sub.textContent = copy.lead;
    document.querySelectorAll("#fleet-perf-tablist .navbtn").forEach(function (btn) {
      var on = btn.getAttribute("data-page") === STATE.page;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
  }

  function ensureBenchmarksTab() {
    var btn = document.getElementById("fleet-tab-benchmarks-btn");
    if (!btn || !window.bootstrap || !window.bootstrap.Tab) return;
    if (btn.classList.contains("active")) return;
    window.bootstrap.Tab.getOrCreateInstance(btn).show();
  }

  function goPage(page) {
    if (!PAGE_COPY[page]) return;
    ensureBenchmarksTab();
    STATE.page = page;
    saveState();
    syncPageChrome();
    if (DOC) paintMain(DOC);
  }

  function planRunFocus(nodeId) {
    goPage("evidence");
    if (nodeId) setRunHost(nodeId);
    setTimeout(function () {
      showRunPanel(true);
      var btn = document.getElementById("fleet-cap-fms-btn") || document.getElementById("fleet-cap-bench-btn");
      if (btn) btn.focus();
    }, 80);
  }

  function handleAction(action, el) {
    if (action === "pickStage") {
      STATE.stage = el.getAttribute("data-id") || STATE.stage;
      saveState();
      if (DOC) paintMain(DOC);
    } else if (action === "pickNode") {
      STATE.node = el.getAttribute("data-id") || STATE.node;
      saveState();
      if (DOC) paintMain(DOC);
    } else if (action === "openStage") {
      STATE.stage = el.getAttribute("data-id") || STATE.stage;
      STATE.page = "threads";
      saveState();
      syncPageChrome();
      if (DOC) paintMain(DOC);
    } else if (action === "openNode") {
      STATE.node = el.getAttribute("data-id") || STATE.node;
      STATE.page = "evidence";
      saveState();
      syncPageChrome();
      if (DOC) paintMain(DOC);
    } else if (action === "planRun") {
      planRunFocus(el.getAttribute("data-id") || "");
    } else if (action === "resetWeights") {
      writePolicy({ baseline: readPolicy().baseline, include_snapshots: readPolicy().include_snapshots, weights: DEFAULT_W });
      if (ON_POLICY) ON_POLICY();
    } else if (action === "insightAct") {
      planRunFocus();
    }
  }

  function onStudioClick(ev) {
    var t = ev.target.closest("[data-page],[data-action]");
    if (!t) return;
    if (t.hasAttribute("data-page")) {
      goPage(t.getAttribute("data-page"));
      return;
    }
    var act = t.getAttribute("data-action");
    if (act) handleAction(act, t);
  }

  function bindStudioEvents() {
    if (BOUND) return;
    BOUND = true;
    ["fleet-perf-tablist", "fleet-perf-studio"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener("click", onStudioClick);
    });
    var plan = document.getElementById("fleet-perf-plan-run");
    if (plan) plan.onclick = planRunFocus;
  }

  function syncPageTitle() {
    var title = document.getElementById("fleet-bench-page-title");
    if (title) title.textContent = "Performance intelligence";
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
    var links = ['<span class="me-2"><strong>This console</strong> <a href="' + esc(here) + '">' + esc(here) + "</a></span>"];
    (peers || []).forEach(function (peer) {
      var url = adminBenchmarksUrl(peer.base_url);
      if (!url) return;
      links.push(
        '<span class="me-2"><strong>' +
          esc(peer.label || peer.id || "peer") +
          '</strong> <a href="' +
          esc(url) +
          '" rel="noopener noreferrer">' +
          esc(url) +
          "</a></span>"
      );
    });
    root.innerHTML = '<p class="mb-1"><strong>Fleet consoles</strong></p><p class="mb-0">' + links.join(" · ") + "</p>";
  }

  function render(doc, opts) {
    if (!doc || !doc.ok) return;
    opts = opts || {};
    DOC = doc;
    ON_POLICY = opts.onPolicyChange || null;
    loadState();
    if (!nodeById(doc, STATE.node)) {
      var first = nodes(doc)[0];
      STATE.node = first ? first.node_id : "local";
    }
    bindStudioEvents();
    syncPageTitle();
    if (opts.peers) renderConsoles(opts.peers);
    updateBaselineSelect(doc);
    updateConnectionBox(doc);
    updateInsightsBadge(doc);
    syncPageChrome();
    paintMain(doc);
    if (opts.comparisonDoc && window.forgeFleetBenchmarksView && typeof window.forgeFleetBenchmarksView.render === "function") {
      window.forgeFleetBenchmarksView.render(opts.comparisonDoc, { peers: opts.peers || [] });
    }
  }

  window.forgeFleetPerformanceView = {
    render: render,
    renderConsoles: renderConsoles,
    readPolicy: readPolicy,
    writePolicy: writePolicy,
    scoreQuery: scoreQuery,
    goPage: goPage,
  };
})();
