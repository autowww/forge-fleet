    function pctOfMaxRaw(val, maxVal) {
      if (val == null || isNaN(val)) return 0;
      var mx = maxVal != null && !isNaN(maxVal) && Number(maxVal) > 0 ? Number(maxVal) : 0;
      if (mx <= 0) return 0;
      return Math.min(100, Math.max(0, (Number(val) / mx) * 100));
    }

    function sortMetricRows(rows) {
      if (!rows || !rows.length) return [];
      return rows
        .slice()
        .sort(function (a, b) {
          return Number(a.t) - Number(b.t);
        });
    }

    /** Average numeric fields per wall-clock bucket; one row per bucket that has ≥1 sample. ``t`` = bucket center ms. */
    function averageMetricRowsIntoBuckets(rows, bucketMs, windowStartMs, windowEndMs) {
      if (!bucketMs || bucketMs <= 0 || windowEndMs <= windowStartMs) return [];
      var buckets = {};
      function addSum(bk, key, val) {
        if (val == null || isNaN(val)) return;
        if (!buckets[bk]) buckets[bk] = { sums: {}, counts: {} };
        var s = buckets[bk].sums;
        var c = buckets[bk].counts;
        s[key] = (s[key] || 0) + Number(val);
        c[key] = (c[key] || 0) + 1;
      }
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        var t = r.t != null && !isNaN(Number(r.t)) ? Number(r.t) : null;
        if (t == null || t < windowStartMs || t > windowEndMs) continue;
        var bk = Math.floor((t - windowStartMs) / bucketMs);
        var maxBk = Math.floor((windowEndMs - windowStartMs) / bucketMs);
        if (bk < 0 || bk > maxBk + 1) continue;
        addSum(bk, "cpu", r.cpu);
        addSum(bk, "mem", r.mem);
        addSum(bk, "tempC", r.tempC);
        addSum(bk, "loadPct", r.loadPct);
        addSum(bk, "diskUi", r.diskUi);
      }
      var out = [];
      var keys = Object.keys(buckets)
        .map(Number)
        .sort(function (a, b) {
          return a - b;
        });
      for (var j = 0; j < keys.length; j++) {
        var bki = keys[j];
        var B = buckets[bki];
        var sums = B.sums;
        var counts = B.counts;
        var center = windowStartMs + bki * bucketMs + bucketMs / 2;
        function avg(k) {
          var cnt = counts[k] || 0;
          if (!cnt) return null;
          return sums[k] / cnt;
        }
        out.push({
          t: center,
          cpu: avg("cpu") != null ? avg("cpu") : 0,
          mem: avg("mem") != null ? avg("mem") : 0,
          tempC: avg("tempC"),
          loadPct: avg("loadPct"),
          diskUi: avg("diskUi"),
        });
      }
      return out;
    }
