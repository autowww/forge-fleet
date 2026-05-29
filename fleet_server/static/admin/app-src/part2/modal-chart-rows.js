    /**
     * Prepare modal series: fixed UTC window from ``doc.window``, bucket averages (5 min for 24h; else nice step).
     */
    function buildModalChartRows(periodKey, rawRows, doc) {
      var win = doc && doc.window && typeof doc.window === "object" ? doc.window : null;
      var t0 = win && win.start_epoch != null ? Number(win.start_epoch) : NaN;
      var t1 = win && win.end_epoch != null ? Number(win.end_epoch) : NaN;
      if (!isFinite(t0) || !isFinite(t1)) {
        return { averagedRows: [], windowStartMs: null, windowEndMs: null, bucketMs: null };
      }
      var windowStartMs = t0 * 1000;
      var windowEndMs = t1 * 1000;
      var sorted = sortMetricRows(rawRows || []);
      var clipped = [];
      for (var i = 0; i < sorted.length; i++) {
        var tr = sorted[i].t;
        if (tr != null && !isNaN(Number(tr)) && Number(tr) >= windowStartMs && Number(tr) <= windowEndMs) {
          clipped.push(sorted[i]);
        }
      }
      var bucketMs =
        periodKey === "last_24_hours"
          ? 5 * 60 * 1000
          : pickNiceBucketMs(windowEndMs - windowStartMs, 556);
      var averagedRows = averageMetricRowsIntoBuckets(clipped, bucketMs, windowStartMs, windowEndMs);
      return {
        averagedRows: averagedRows,
        windowStartMs: windowStartMs,
        windowEndMs: windowEndMs,
        bucketMs: bucketMs,
      };
    }
