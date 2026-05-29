    var refreshMetricsBtn = document.getElementById("fleet-refresh-metrics-btn");
    if (refreshMetricsBtn) {
      refreshMetricsBtn.addEventListener("click", function () {
        loadSnapshot().then(function () {
          scheduleNext();
        });
      });
    }

    var fleetSvcRefreshBtn = document.getElementById("fleet-svc-refresh-btn");
    if (fleetSvcRefreshBtn) {
      fleetSvcRefreshBtn.addEventListener("click", function () {
        loadSnapshot().then(function () {
          scheduleNext();
        });
      });
    }

    var fleetLoadChartEl = document.getElementById("fleet-load-chart");
    if (fleetLoadChartEl) {
      fleetLoadChartEl.addEventListener("click", function () {
        openFleetTelemetryHistoryModal();
      });
      fleetLoadChartEl.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          openFleetTelemetryHistoryModal();
        }
      });
    }

    var fleetAdminTablist = document.getElementById("fleet-admin-tablist");
    if (fleetAdminTablist) {
      fleetAdminTablist.addEventListener("shown.bs.tab", function (ev) {
        var t = ev.target;
        if (!t || t.getAttribute("role") !== "tab") return;
        var bid = t.getAttribute("id") || "";
        if (bid === "fleet-tab-overview-btn") renderFleetChart();
        if (bid === "fleet-tab-containers-btn") renderOrchestrationChart();
      });
    }

    var fleetSysCopy = document.getElementById("fleet-system-update-copy");
    if (fleetSysCopy) {
      fleetSysCopy.addEventListener("click", function () {
        var pre = document.getElementById("fleet-system-update-command");
        var t = pre ? pre.textContent : "";
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(t).then(
            function () {
              fleetSysCopy.textContent = "Copied";
              window.setTimeout(function () {
                fleetSysCopy.textContent = "Copy command";
              }, 2000);
            },
            function () {
              /* ignore */
            }
          );
        }
      });
    }
