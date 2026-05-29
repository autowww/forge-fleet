    /**
     * Build SVG path strings for CPU, RAM, and %%-of-max (temp, load, disk) series.
     * Optional ``windowOpts``: { windowStartMs, windowEndMs } maps x to full period (sparse data leaves gap).
     */
    function fleetTelemetryGridAndPaths(chartRows, mm, w, h, padL, padR, padT, padB, windowOpts) {
      var iw = w - padL - padR;
      var ih = h - padT - padB;
      var n = chartRows.length;
      var winS = windowOpts && windowOpts.windowStartMs != null ? Number(windowOpts.windowStartMs) : null;
      var winE = windowOpts && windowOpts.windowEndMs != null ? Number(windowOpts.windowEndMs) : null;
      var winMode = winS != null && winE != null && winE > winS;
      if (!n) {
        var gridPartsEmpty = [];
        chartTickPercents().forEach(function (tp) {
          var gy = chartPctToY(tp, padT, ih);
          gridPartsEmpty.push(
            "<line x1=\"" +
              padL +
              "\" y1=\"" +
              gy.toFixed(2) +
              "\" x2=\"" +
              (padL + iw) +
              "\" y2=\"" +
              gy.toFixed(2) +
              "\" stroke=\"currentColor\" stroke-opacity=\"0.11\" stroke-width=\"1\"/>"
          );
          gridPartsEmpty.push(
            "<text x=\"" +
              (padL - 5) +
              "\" y=\"" +
              (gy + 3).toFixed(2) +
              "\" fill=\"currentColor\" opacity=\"0.48\" font-size=\"9\" text-anchor=\"end\">" +
              tp +
              "</text>"
          );
        });
        return {
          gridInner: gridPartsEmpty.join(""),
          dCpu: "",
          dMem: "",
          dTemp: "",
          dLoad: "",
          dDisk: "",
          w: w,
          h: h,
        };
      }
      var tMin;
      var tMax;
      var span;
      if (winMode) {
        tMin = winS;
        tMax = winE;
        span = Math.max(1, tMax - tMin);
      } else {
        tMin = chartRows[0].t != null ? chartRows[0].t : 0;
        tMax = chartRows[n - 1].t != null ? chartRows[n - 1].t : tMin + 1;
        span = Math.max(1, tMax - tMin);
      }
      var xsTime = [];
      for (var xi = 0; xi < n; xi++) {
        var rw = chartRows[xi];
        var ti = rw && rw.t != null ? rw.t : tMin;
        xsTime.push(padL + ((ti - tMin) / span) * iw);
      }
      var useIdxX = false;
      if (!winMode && n >= 2) {
        var spanMs = tMax - tMin;
        var dupc = 0;
        for (var xj = 1; xj < n; xj++) {
          if (Math.abs(xsTime[xj] - xsTime[xj - 1]) < 0.6) dupc++;
        }
        if (spanMs < 2000 || dupc >= Math.max(2, Math.floor(n * 0.35))) useIdxX = true;
      }
      function xAt(i) {
        if (useIdxX) return padL + (n <= 1 ? 0 : (i / Math.max(1, n - 1)) * iw);
        return xsTime[i];
      }
      var rawC = [];
      var rawM = [];
      var rawT = [];
      var rawL = [];
      var rawD = [];
      for (var ri = 0; ri < n; ri++) {
        var rowR = chartRows[ri];
        rawC.push(rowR && rowR.cpu != null && !isNaN(rowR.cpu) ? Number(rowR.cpu) : 0);
        rawM.push(rowR && rowR.mem != null && !isNaN(rowR.mem) ? Number(rowR.mem) : 0);
        rawT.push(pctOfMaxRaw(rowR && rowR.tempC, mm.tempC));
        rawL.push(pctOfMaxRaw(rowR && rowR.loadPct, mm.loadPct));
        rawD.push(pctOfMaxRaw(rowR && rowR.diskUi, mm.diskUi));
      }
      var dCpu;
      var dMem;
      var dTemp;
      var dLoad;
      var dDisk;
      if (n === 1) {
        var yc0 = chartPctToY(rawC[0], padT, ih);
        var ym0 = chartPctToY(rawM[0], padT, ih);
        var yt0 = chartPctToY(rawT[0], padT, ih);
        var yl0 = chartPctToY(rawL[0], padT, ih);
        var yd0 = chartPctToY(rawD[0], padT, ih);
        var xFull = (padL + iw).toFixed(2);
        dCpu = "M " + padL + " " + yc0.toFixed(2) + " L " + xFull + " " + yc0.toFixed(2);
        dMem = "M " + padL + " " + ym0.toFixed(2) + " L " + xFull + " " + ym0.toFixed(2);
        dTemp = "M " + padL + " " + yt0.toFixed(2) + " L " + xFull + " " + yt0.toFixed(2);
        dLoad = "M " + padL + " " + yl0.toFixed(2) + " L " + xFull + " " + yl0.toFixed(2);
        dDisk = "M " + padL + " " + yd0.toFixed(2) + " L " + xFull + " " + yd0.toFixed(2);
      } else {
        var ptsCpu = [];
        var ptsMem = [];
        var ptsTemp = [];
        var ptsLoad = [];
        var ptsDisk = [];
        for (var i = 0; i < n; i++) {
          var xi2 = xAt(i);
          ptsCpu.push({ x: xi2, y: chartPctToY(rawC[i], padT, ih) });
          ptsMem.push({ x: xi2, y: chartPctToY(rawM[i], padT, ih) });
          ptsTemp.push({ x: xi2, y: chartPctToY(rawT[i], padT, ih) });
          ptsLoad.push({ x: xi2, y: chartPctToY(rawL[i], padT, ih) });
          ptsDisk.push({ x: xi2, y: chartPctToY(rawD[i], padT, ih) });
        }
        dCpu = chartPolylineD(ptsCpu);
        dMem = chartPolylineD(ptsMem);
        dTemp = chartPolylineD(ptsTemp);
        dLoad = chartPolylineD(ptsLoad);
        dDisk = chartPolylineD(ptsDisk);
      }
      var gridParts = [];
      chartTickPercents().forEach(function (tp) {
        var gy = chartPctToY(tp, padT, ih);
        gridParts.push(
          "<line x1=\"" +
            padL +
            "\" y1=\"" +
            gy.toFixed(2) +
            "\" x2=\"" +
            (padL + iw) +
            "\" y2=\"" +
            gy.toFixed(2) +
            "\" stroke=\"currentColor\" stroke-opacity=\"0.11\" stroke-width=\"1\"/>"
        );
        gridParts.push(
          "<text x=\"" +
            (padL - 5) +
            "\" y=\"" +
            (gy + 3).toFixed(2) +
            "\" fill=\"currentColor\" opacity=\"0.48\" font-size=\"9\" text-anchor=\"end\">" +
            tp +
            "</text>"
        );
      });
      return {
        gridInner: gridParts.join(""),
        dCpu: dCpu,
        dMem: dMem,
        dTemp: dTemp,
        dLoad: dLoad,
        dDisk: dDisk,
        w: w,
        h: h,
      };
    }
