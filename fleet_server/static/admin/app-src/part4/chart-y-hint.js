    function refreshChartYHint() {
      var el = document.getElementById("fleet-chart-y-hint");
      if (!el) return;
      var base =
        "Older left · recent right · SQLite history + live snapshot tail each refresh · ";
      el.textContent =
        base + (chartLinearYEnabled() ? "Y linear 0–100%" : "Y scale 0–1–10–50–100");
    }
