    function loadMetrics(host) {
      var c = host.cpus != null ? Number(host.cpus) : null;
      var la = host.loadavg;
      if (!Array.isArray(la) || la.length < 3 || c == null || isNaN(c) || c < 1) return null;
      var l1 = Number(la[0]);
      var l5 = Number(la[1]);
      var l15 = Number(la[2]);
      if (isNaN(l1) || isNaN(l5) || isNaN(l15)) return null;
      var sc = getLoadScaleDenominator(c);
      var den = sc.den;
      return {
        l1: l1,
        l5: l5,
        l15: l15,
        cpus: c,
        scaleDen: den,
        scaleSaved: sc.saved,
        pct1: Math.min(100, Math.max(0, (100 * l1) / den)),
        pct5: Math.min(100, Math.max(0, (100 * l5) / den)),
        pct15: Math.min(100, Math.max(0, (100 * l15) / den)),
      };
    }

    /** When ``loadMetrics`` is null but ``/proc``-style loadavg exists (e.g. bad CPU count), still show bars. */
    function approxLoadMetrics(host) {
      if (loadMetrics(host) != null) return null;
      var la = host && host.loadavg;
      if (!Array.isArray(la) || la.length < 3) return null;
      var l1 = Number(la[0]);
      var l5 = Number(la[1]);
      var l15 = Number(la[2]);
      if (isNaN(l1) || isNaN(l5) || isNaN(l15)) return null;
      var c = host.cpus != null ? Number(host.cpus) : NaN;
      var den = isFinite(c) && c >= 1 ? c : 1;
      return {
        l1: l1,
        l5: l5,
        l15: l15,
        cpus: den,
        scaleDen: den,
        scaleSaved: false,
        pct1: Math.min(100, Math.max(0, (100 * l1) / den)),
        pct5: Math.min(100, Math.max(0, (100 * l5) / den)),
        pct15: Math.min(100, Math.max(0, (100 * l15) / den)),
        approx: true,
      };
    }

    function hostLoadForUi(host) {
      return loadMetrics(host) || approxLoadMetrics(host);
    }
