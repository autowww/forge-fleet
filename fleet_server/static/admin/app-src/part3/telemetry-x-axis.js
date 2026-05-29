    /** UTC x-axis ticks and labels below the plot (returns inner SVG fragment). */
    function fleetTelemetryXAxisMarkup(windowStartMs, windowEndMs, padL, iw, axisTopY, periodKey) {
      if (windowStartMs == null || windowEndMs == null || windowEndMs <= windowStartMs) return "";
      var span = windowEndMs - windowStartMs;
      var tickCount = 7;
      var parts = [];
      var mode = "mdhm";
      if (span <= 36 * 60 * 60 * 1000) mode = "hm";
      else if (span <= 14 * 24 * 60 * 60 * 1000) mode = "mdhm";
      else mode = "md";
      for (var i = 0; i < tickCount; i++) {
        var u = tickCount <= 1 ? 0 : i / (tickCount - 1);
        var tMs = windowStartMs + u * span;
        var x = padL + u * iw;
        parts.push(
          "<line x1=\"" +
            x.toFixed(2) +
            "\" y1=\"" +
            axisTopY.toFixed(2) +
            "\" x2=\"" +
            x.toFixed(2) +
            "\" y2=\"" +
            (axisTopY + 5).toFixed(2) +
            "\" stroke=\"currentColor\" stroke-opacity=\"0.35\" stroke-width=\"1\"/>"
        );
        var label = "";
        try {
          var d = new Date(tMs);
          if (mode === "hm") {
            label = d.toLocaleString(undefined, {
              timeZone: "UTC",
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
            });
          } else if (mode === "mdhm") {
            label = d.toLocaleString(undefined, {
              timeZone: "UTC",
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
            });
          } else {
            label = d.toLocaleString(undefined, {
              timeZone: "UTC",
              year: "numeric",
              month: "short",
              day: "numeric",
            });
          }
        } catch (_e) {
          label = "";
        }
        parts.push(
          "<text x=\"" +
            x.toFixed(2) +
            "\" y=\"" +
            (axisTopY + 16).toFixed(2) +
            "\" fill=\"currentColor\" opacity=\"0.55\" font-size=\"8.5\" text-anchor=\"middle\">" +
            esc(label) +
            "</text>"
        );
      }
      return "<g class=\"fleet-tel-x-axis\" aria-hidden=\"true\">" + parts.join("") + "</g>";
    }
