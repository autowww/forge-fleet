    function memQuarterFills(usedPct) {
      var p = usedPct == null || isNaN(usedPct) ? 0 : Math.min(100, Math.max(0, Number(usedPct)));
      var out = [];
      for (var i = 0; i < 4; i++) {
        var lo = i * 25;
        var hi = (i + 1) * 25;
        var h = 0;
        if (p > lo) {
          h = p >= hi ? 100 : (100 * (p - lo)) / 25;
        }
        out.push(h);
      }
      return out;
    }
