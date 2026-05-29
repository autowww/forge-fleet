    function chartLinearYEnabled() {
      try {
        return localStorage.getItem(LS_CHART_LINEAR_Y) === "1";
      } catch (_e) {
        return false;
      }
    }

    /**
     * Map 0–100%% to normalized height g in [0,1] (piecewise linear: 10 lower, 50 at 75%% band).
     * y = padT + ih - g*ih so larger g is higher on screen.
     */
    function chartPctNormG(p) {
      var u = Math.min(100, Math.max(0, Number(p)));
      var g10 = 0.38;
      if (u <= 10) return (u / 10) * g10;
      if (u <= 50) return g10 + ((u - 10) / 40) * (0.75 - g10);
      return 0.75 + ((u - 50) / 50) * 0.25;
    }

    function chartPctNormGLinear(p) {
      var u = Math.min(100, Math.max(0, Number(p)));
      return u / 100;
    }

    function chartPctToY(p, padT, ih) {
      var g = chartLinearYEnabled() ? chartPctNormGLinear(p) : chartPctNormG(p);
      return padT + ih - g * ih;
    }

    function chartTickPercents() {
      return [0, 1, 10, 50, 100];
    }

    /**
     * Downsample to ``maxPts`` targets along the visible window. Each target time ``tt``
     * takes the **nearest** raw sample (by timestamp), not linear interpolation — so past
     * vertices stay tied to real polls and do not “breathe” when new points arrive.
     */
    function chartBufResampleTime(buf, maxPts) {
      if (!buf || !buf.length) return [];
      if (buf.length <= maxPts) return buf.slice();
      var t0 = Number(buf[0].t);
      var t1 = Number(buf[buf.length - 1].t);
      var span = Math.max(1, t1 - t0);
      var out = [];
      for (var j = 0; j < maxPts; j++) {
        var u = maxPts <= 1 ? 0 : j / (maxPts - 1);
        var tt = t0 + u * span;
        var best = buf[0];
        var bestD = Math.abs(Number(buf[0].t) - tt);
        for (var i = 1; i < buf.length; i++) {
          var d = Math.abs(Number(buf[i].t) - tt);
          if (d < bestD) {
            bestD = d;
            best = buf[i];
          }
        }
        out.push({
          t: tt,
          cpu: best.cpu,
          mem: best.mem,
          tempC: best.tempC,
          loadPct: best.loadPct,
          diskUi: best.diskUi,
        });
      }
      return out;
    }

    /** Open polyline (piecewise linear) — stable under sliding windows (no spline tangents). */
    function chartPolylineD(pts) {
      if (!pts || !pts.length) return "";
      if (pts.length === 1) {
        return "M " + pts[0].x + " " + pts[0].y;
      }
      var d = "M " + pts[0].x + " " + pts[0].y;
      for (var i = 1; i < pts.length; i++) {
        d += " L " + pts[i].x + " " + pts[i].y;
      }
      return d;
    }

    /** Catmull–Rom segment → SVG cubic Bézier through points (open curve). */
    function chartSmoothPathD(pts) {
      if (!pts || pts.length < 2) return "";
      var n = pts.length;
      if (n === 2) {
        return "M " + pts[0].x + " " + pts[0].y + " L " + pts[1].x + " " + pts[1].y;
      }
      var d = "M " + pts[0].x + " " + pts[0].y;
      for (var i = 0; i < n - 1; i++) {
        var p0 = pts[Math.max(0, i - 1)];
        var p1 = pts[i];
        var p2 = pts[i + 1];
        var p3 = pts[Math.min(n - 1, i + 2)];
        var c1x = p1.x + (p2.x - p0.x) / 6;
        var c1y = p1.y + (p2.y - p0.y) / 6;
        var c2x = p2.x - (p3.x - p1.x) / 6;
        var c2y = p2.y - (p3.y - p1.y) / 6;
        d += " C " + c1x + " " + c1y + " " + c2x + " " + c2y + " " + p2.x + " " + p2.y;
      }
      return d;
    }

    /** Ensure every row has monotonic ms timestamps (fixes vertical collapse when t missing or stuck). */
    function chartNormalizeTimes(buf) {
      if (!buf || !buf.length) return [];
      var out = [];
      var lastT = null;
      for (var i = 0; i < buf.length; i++) {
        var r = buf[i];
        var t = r.t != null && !isNaN(Number(r.t)) ? Number(r.t) : null;
        if (t == null) {
          t = lastT != null ? lastT + POLL_MS : Date.now() - (buf.length - 1 - i) * POLL_MS;
        }
        if (lastT != null && t <= lastT) t = lastT + 1;
        lastT = t;
        out.push({
          t: t,
          cpu: r.cpu,
          mem: r.mem,
          tempC: r.tempC,
          loadPct: r.loadPct,
          diskUi: r.diskUi,
        });
      }
      return out;
    }
