              break;
            }
          }
          if (!dup) templates.push(row);
        }
        var ver = __fleetReqTemplatesDoc && __fleetReqTemplatesDoc.version != null ? __fleetReqTemplatesDoc.version : 1;
        renderFleetReqTemplatesTable({ ok: true, version: ver, templates: templates });
        var modalEl = document.getElementById("fleet-req-template-modal");
        if (modalEl && typeof bootstrap !== "undefined" && bootstrap.Modal) {
          var mi = bootstrap.Modal.getInstance(modalEl);
          if (mi) mi.hide();
          else bootstrap.Modal.getOrCreateInstance(modalEl).hide();
        }
      });
    }
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
    document.addEventListener("visibilitychange", function () {
      scheduleNext();
    });

    var fleetA11yModalEl = document.getElementById("fleet-a11y-overview-modal");
    if (fleetA11yModalEl) {
      fleetA11yModalEl.addEventListener("show.bs.modal", function () {
        fillFleetA11yOverviewStubs();
      });
    }

    setInterval(tick, 500);
    loadSnapshot().then(function () { scheduleNext(); });
  })();
