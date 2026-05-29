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
