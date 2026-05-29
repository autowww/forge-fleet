    function renderFleetJobsPager(data, rows) {
      var pager = document.getElementById("fleet-jobs-pager");
      if (!pager) return;
      var jtot = data.jobs_recent_total != null ? Number(data.jobs_recent_total) : 0;
      var jlim = data.jobs_recent_limit != null ? Number(data.jobs_recent_limit) : fleetJobsPageSize;
      var joff = data.jobs_recent_offset != null ? Number(data.jobs_recent_offset) : fleetJobsOffset;
      if (!isNaN(jlim) && jlim > 0) fleetJobsPageSize = jlim;
      if (!isNaN(joff) && joff >= 0) fleetJobsOffset = joff;
      if (jtot <= 0) {
        pager.innerHTML = "";
        return;
      }
      var n = rows.length;
      var start = n === 0 ? 0 : joff + 1;
      var end = joff + n;
      var prevDis = joff <= 0 ? " disabled" : "";
      var nextDis = end >= jtot ? " disabled" : "";
      pager.innerHTML =
        '<nav class="d-flex flex-wrap align-items-center justify-content-between gap-2 small" aria-label="Job pages">' +
        '<span class="text-body-secondary">Showing <strong>' +
        start +
        "</strong>–<strong>" +
        end +
        '</strong> of <strong>' +
        jtot +
        '</strong> · ' +
        jlim +
        ' per page</span>' +
        '<div class="btn-group btn-group-sm" role="group">' +
        '<button type="button" class="btn btn-outline-secondary fleet-jobs-page-prev"' +
        prevDis +
        '>Previous</button>' +
        '<button type="button" class="btn btn-outline-secondary fleet-jobs-page-next"' +
        nextDis +
        '>Next</button>' +
        "</div></nav>";
    }
