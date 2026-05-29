    var NICE_BUCKET_MS = [
      60 * 1000,
      2 * 60 * 1000,
      3 * 60 * 1000,
      5 * 60 * 1000,
      10 * 60 * 1000,
      15 * 60 * 1000,
      20 * 60 * 1000,
      30 * 60 * 1000,
      60 * 60 * 1000,
      2 * 60 * 60 * 1000,
      3 * 60 * 60 * 1000,
      4 * 60 * 60 * 1000,
      6 * 60 * 60 * 1000,
      8 * 60 * 60 * 1000,
      12 * 60 * 60 * 1000,
      24 * 60 * 60 * 1000,
      2 * 24 * 60 * 60 * 1000,
      7 * 24 * 60 * 60 * 1000,
    ];

    function pickNiceBucketMs(windowMs, innerWidthPx) {
      var iwPx = innerWidthPx != null && innerWidthPx > 0 ? innerWidthPx : 556;
      var targetBuckets = Math.round(iwPx / 46);
      targetBuckets = Math.max(24, Math.min(160, targetBuckets));
      var ideal = windowMs / Math.max(1, targetBuckets);
      var best = NICE_BUCKET_MS[Math.floor(NICE_BUCKET_MS.length / 2)];
      var bestScore = Infinity;
      for (var i = 0; i < NICE_BUCKET_MS.length; i++) {
        var step = NICE_BUCKET_MS[i];
        var nb = windowMs / step;
        if (nb > 220 || nb < 6) continue;
        var lo = ideal * 0.65;
        var hi = ideal * 1.75;
        var score = step < lo ? lo - step : step > hi ? step - hi : Math.abs(step - ideal);
        if (score < bestScore) {
          bestScore = score;
          best = step;
        }
      }
      if (bestScore < Infinity) return best;
      for (var j = 0; j < NICE_BUCKET_MS.length; j++) {
        var st = NICE_BUCKET_MS[j];
        var nbb = windowMs / st;
        if (nbb <= 220 && nbb >= 3) return st;
      }
      return 60 * 60 * 1000;
    }
