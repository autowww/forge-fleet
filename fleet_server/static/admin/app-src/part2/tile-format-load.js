    function tileMark(svg, hiddenLabel) {
      if (hiddenLabel == null || String(hiddenLabel).trim() === "") return svg;
      return svg + "<span class=\"visually-hidden\">" + esc(hiddenLabel) + "</span>";
    }

    function fmtLoadAvg1m(x) {
      if (x == null || isNaN(Number(x))) return "—";
      var n = Number(x);
      var t = Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(2);
      return String(t);
    }

    function getLoadScaleDenominator(liveCpus) {
      var c = liveCpus != null && !isNaN(Number(liveCpus)) && Number(liveCpus) > 0 ? Number(liveCpus) : 1;
      var raw = localStorage.getItem(LS_LOAD_SCALE);
      if (raw == null || String(raw).trim() === "") {
        return { den: c, saved: false, liveCpus: c };
      }
      var n = parseFloat(String(raw).trim());
      if (!isFinite(n) || n <= 0) {
        return { den: c, saved: false, liveCpus: c };
      }
      return { den: n, saved: true, liveCpus: c };
    }

    function mergeLoadPeakPct(pct) {
      if (pct == null || isNaN(pct)) return;
      var v = Math.round(Number(pct));
      var cur = parseFloat(localStorage.getItem(LS_LOAD_PEAK) || "");
      if (!isFinite(cur)) cur = 0;
      if (v > cur) localStorage.setItem(LS_LOAD_PEAK, String(v));
    }
