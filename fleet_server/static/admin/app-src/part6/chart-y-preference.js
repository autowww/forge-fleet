    var linearY = document.getElementById("fleet-chart-linear-y");
    if (linearY) {
      try {
        linearY.checked = localStorage.getItem(LS_CHART_LINEAR_Y) === "1";
      } catch (_e) {
        linearY.checked = false;
      }
      linearY.addEventListener("change", function () {
        try {
          if (linearY.checked) localStorage.setItem(LS_CHART_LINEAR_Y, "1");
          else localStorage.removeItem(LS_CHART_LINEAR_Y);
        } catch (_e) {
          /* ignore */
        }
        refreshChartYHint();
        renderFleetChart();
      });
    }
