    function renderOrchestrationChart() {
      var el = document.getElementById("fleet-orch-chart");
      if (!el) return;
      if (!orchBuf.length) {
        el.innerHTML =
          "<svg class=\"fleet-chart-svg\" xmlns=\"http://www.w3.org/2000/svg\" width=\"100%\" height=\"100%\" viewBox=\"0 0 600 88\"><text x=\"32\" y=\"44\" fill=\"currentColor\" opacity=\"0.45\" font-size=\"11\">No workload history in SQLite yet (telemetry_samples).</text></svg>";
        return;
      }
      var w = 600;
      var h = 88;
      var padL = 32;
      var padR = 8;
      var padT = 6;
      var padB = 12;
      var iw = w - padL - padR;
      var ih = h - padT - padB;
      var n = orchBuf.length;
      var tMin = orchBuf[0].t;
      var tMax = orchBuf[n - 1].t;
      var span = Math.max(1, tMax - tMin);
      var maxV = 1;
      for (var i = 0; i < n; i++) {
        maxV = Math.max(maxV, Number(orchBuf[i].managed) || 0, Number(orchBuf[i].jobs) || 0);
      }
      maxV = Math.ceil(maxV * 1.08) || 1;
      function yFor(v) {
        var vv = Math.min(maxV, Math.max(0, Number(v)));
        return padT + ih - (vv / maxV) * ih;
      }
      function xFor(i) {
        var ti = orchBuf[i].t;
        return padL + ((ti - tMin) / span) * iw;
      }
      var ptsM = [];
      var ptsJ = [];
      for (var j = 0; j < n; j++) {
        var xj = xFor(j);
        ptsM.push({ x: xj, y: yFor(orchBuf[j].managed) });
        ptsJ.push({ x: xj, y: yFor(orchBuf[j].jobs) });
      }
      var dM;
      var dJ;
      if (n < 2) {
        var ym = yFor(orchBuf[0].managed);
        var yj = yFor(orchBuf[0].jobs);
        dM = "M " + padL + " " + ym + " L " + (padL + iw) + " " + ym;
        dJ = "M " + padL + " " + yj + " L " + (padL + iw) + " " + yj;
      } else {
        dM = chartSmoothPathD(ptsM);
        dJ = chartSmoothPathD(ptsJ);
      }
      var svg =
        "<svg class=\"fleet-chart-svg\" xmlns=\"http://www.w3.org/2000/svg\" width=\"100%\" height=\"100%\" preserveAspectRatio=\"none\" viewBox=\"0 0 " +
        w +
        " " +
        h +
        "\">" +
        "<text x=\"" +
        padL +
        "\" y=\"" +
        (padT + 10) +
        "\" fill=\"currentColor\" opacity=\"0.42\" font-size=\"9\">0–" +
        esc(String(maxV)) +
        " (count)</text>" +
        "<path fill=\"none\" stroke=\"#34d399\" stroke-width=\"2\" stroke-linejoin=\"round\" d=\"" +
        esc(dM) +
        "\"/>" +
        "<path fill=\"none\" stroke=\"#38bdf8\" stroke-width=\"2\" stroke-linejoin=\"round\" d=\"" +
        esc(dJ) +
        "\"/>" +
        "</svg>";
      el.innerHTML = svg;
    }
