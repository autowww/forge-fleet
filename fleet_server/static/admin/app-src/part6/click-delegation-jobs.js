    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.getAttribute) return;
      var detBtn = t.closest ? t.closest(".fleet-job-detail-btn") : null;
      if (detBtn && detBtn.getAttribute) {
        ev.preventDefault();
        var jid = detBtn.getAttribute("data-job-id");
        if (jid) void openFleetJobDetail(jid);
        return;
      }
      var prevPg = t.closest ? t.closest(".fleet-jobs-page-prev") : null;
      if (prevPg && !prevPg.disabled) {
        ev.preventDefault();
        fleetJobsOffset = Math.max(0, fleetJobsOffset - fleetJobsPageSize);
        void loadSnapshot().then(scheduleNext);
        return;
      }
      var nextPg = t.closest ? t.closest(".fleet-jobs-page-next") : null;
      if (nextPg && !nextPg.disabled) {
        ev.preventDefault();
        fleetJobsOffset += fleetJobsPageSize;
        void loadSnapshot().then(scheduleNext);
        return;
      }
    });
