    var __fleetLastPowerTotalW = null;

    function renderPowerTile(host, energyLedger) {
      __fleetLastPowerTotalW = null;
      var en = (host && host.energy) || {};
      var raplOk = en.rapl_available === true && en.rapl_package_uj != null && !isNaN(Number(en.rapl_package_uj));
      var uj = raplOk ? Number(en.rapl_package_uj) : null;
      var gpuW = en.gpu_power_draw_w_sum != null && !isNaN(Number(en.gpu_power_draw_w_sum)) ? Number(en.gpu_power_draw_w_sum) : null;
      var tMs = host && host.time_utc ? Date.parse(String(host.time_utc)) : NaN;

      var raplW = null;
      if (raplOk && uj != null && !isNaN(tMs)) {
        if (__fleetRaplPrev.uj != null && __fleetRaplPrev.tMs != null) {
          var dt = (tMs - __fleetRaplPrev.tMs) / 1000;
          if (dt >= 0.2 && dt <= 120) {
            var duj = uj - __fleetRaplPrev.uj;
            if (duj >= 0) {
              raplW = (duj / 1e6) / dt;
              if (!isFinite(raplW) || raplW < 0 || raplW > 1200) raplW = null;
            }
          }
        }
        __fleetRaplPrev.uj = uj;
        __fleetRaplPrev.tMs = tMs;
      }

      var raplInstant =
        en.rapl_instant_w != null && !isNaN(Number(en.rapl_instant_w)) && Number(en.rapl_instant_w) > 0
          ? Number(en.rapl_instant_w)
          : null;
      if (raplW == null && raplInstant != null) raplW = raplInstant;

      var totalW = null;
      if (raplW != null && gpuW != null) totalW = raplW + gpuW;
      else if (raplW != null) totalW = raplW;
      else if (gpuW != null) totalW = gpuW;

      var heroW = null;
      if (totalW != null && !isNaN(Number(totalW))) heroW = Number(totalW);
      else if (gpuW != null && !isNaN(Number(gpuW))) heroW = Number(gpuW);

      var hasSignal = totalW != null || raplOk || gpuW != null;
      var hintLine = formatLedgerKwhShort(energyLedger) || formatLedgerKwhLine(energyLedger);

      if (!hasSignal) {
        var rr = en.rapl_reason != null ? String(en.rapl_reason).trim() : "";
        __fleetPowerDiagRaplReason = rr;
        return "";
      }

      __fleetLastPowerTotalW = heroW;
      var heatIn = heroW != null ? Math.min(100, Math.max(0, (heroW / 320) * 100)) : 0;
      var pHeat = heat3(heatIn);
      var pwDisp = heroW != null && !isNaN(heroW) ? fleetPowerWAnim.widthForRender(heroW) : null;
      var wPow =
        pwDisp != null && !isNaN(pwDisp)
          ? Math.round(Number(pwDisp))
          : heroW != null && !isNaN(heroW)
            ? Math.round(Number(heroW))
            : null;
      var main =
        wPow != null
          ? '<span id="fleet-power-val" class="fleet-mono">' + esc(String(wPow)) + " W</span>"
          : '<span id="fleet-power-val" class="fleet-mono">—</span>';
      var memParts = [];
      if (raplW != null) memParts.push("Processor about " + esc(fmtWatts(raplW)) + " W");
      else if (raplOk) memParts.push("Processor: hang on — watts fill in on the next refresh");
      if (gpuW != null) memParts.push("GPU about " + esc(fmtWatts(gpuW)) + " W");
      var memLine = memParts.length ? memParts.join(" · ") : "Power draw";
      var rrOn = en.rapl_reason != null ? String(en.rapl_reason).trim() : "";
      __fleetPowerDiagRaplReason = rrOn;
      return (
        '<div class="fleet-tile fleet-tile--power-' +
        pHeat +
        '">' +
        '<div class="fleet-tile__brand">' +
        tileMark(MARK_POWER, "Power") +
        "</div>" +
        '<div class="fleet-tile__value fleet-mono">' +
        main +
        "</div>" +
        '<div class="fleet-tile__mem">' +
        esc(memLine) +
        "</div>" +
        '<div class="fleet-tile__hint">' +
        hintLine +
        "</div>" +
        '<p class="small mb-1 mt-1"><button type="button" class="btn btn-link btn-sm p-0 fleet-power-open-diag">How to see watts / diagnostics</button></p>' +
        "</div>"
      );
    }
