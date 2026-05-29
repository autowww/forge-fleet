    function samplesToMetricRows(samples, tCutMs) {
      var out = [];
      var now = Date.now();
      var cut = tCutMs != null ? now - tCutMs : null;
      for (var i = 0; i < samples.length; i++) {
        var sample = samples[i];
        if (!sample) continue;
        var tsMs = Number(sample.ts) * 1000;
        if (isNaN(tsMs)) continue;
        if (cut != null && tsMs < cut) continue;
        var h = sample.host && typeof sample.host === "object" ? sample.host : {};
        var met = hostMetricsForChart(h);
        out.push({
          t: tsMs,
          cpu: met.cpu,
          mem: met.mem,
          tempC: met.tempC,
          loadPct: met.loadPct,
          diskUi: met.diskUi,
        });
      }
      return out;
    }

    function renderTelemetrySvgMarkup(gp, strokeScale, idPrefix, xAxisMarkup) {
      var sw = strokeScale != null ? strokeScale : 2;
      var swThin = Math.max(1.25, sw - 0.65);
      var p = idPrefix != null && String(idPrefix).trim() !== "" ? String(idPrefix).trim() + "-" : "";
      var xa = xAxisMarkup != null ? String(xAxisMarkup) : "";
      return (
        "<g id=\"" +
        esc(p + "fleet-chart-grid") +
        "\">" +
        gp.gridInner +
        "</g>" +
        "<path id=\"" +
        esc(p + "fleet-chart-cpu") +
        "\" fill=\"none\" stroke=\"#34d399\" stroke-width=\"" +
        sw +
        "\" stroke-linejoin=\"round\" stroke-linecap=\"round\" vector-effect=\"non-scaling-stroke\" shape-rendering=\"geometricPrecision\" d=\"" +
        esc(gp.dCpu) +
        "\"/>" +
        "<path id=\"" +
        esc(p + "fleet-chart-mem") +
        "\" fill=\"none\" stroke=\"#38bdf8\" stroke-width=\"" +
        sw +
        "\" stroke-linejoin=\"round\" stroke-linecap=\"round\" vector-effect=\"non-scaling-stroke\" shape-rendering=\"geometricPrecision\" d=\"" +
        esc(gp.dMem) +
        "\"/>" +
        "<path id=\"" +
        esc(p + "fleet-chart-temp") +
        "\" fill=\"none\" stroke=\"#fb923c\" stroke-width=\"" +
        swThin +
        "\" stroke-linejoin=\"round\" stroke-linecap=\"round\" vector-effect=\"non-scaling-stroke\" shape-rendering=\"geometricPrecision\" d=\"" +
        esc(gp.dTemp) +
        "\"/>" +
        "<path id=\"" +
        esc(p + "fleet-chart-load") +
        "\" fill=\"none\" stroke=\"#eab308\" stroke-width=\"" +
        swThin +
        "\" stroke-linejoin=\"round\" stroke-linecap=\"round\" vector-effect=\"non-scaling-stroke\" shape-rendering=\"geometricPrecision\" d=\"" +
        esc(gp.dLoad) +
        "\"/>" +
        "<path id=\"" +
        esc(p + "fleet-chart-disk") +
        "\" fill=\"none\" stroke=\"#c084fc\" stroke-width=\"" +
        swThin +
        "\" stroke-linejoin=\"round\" stroke-linecap=\"round\" vector-effect=\"non-scaling-stroke\" shape-rendering=\"geometricPrecision\" d=\"" +
        esc(gp.dDisk) +
        "\"/>" +
        xa
      );
    }
