    /** LLM thermal throttle waits (SQLite), same preset keys as ``cooldown_summary`` meta — not which LLM host is configured. */
    function renderCooldownTile(cs) {
      if (!cs || typeof cs !== "object") return "";
      var td = cs.today && typeof cs.today === "object" ? cs.today : null;
      var tw = cs.this_week && typeof cs.this_week === "object" ? cs.this_week : null;
      var tm = cs.this_month && typeof cs.this_month === "object" ? cs.this_month : null;
      var ty = cs.this_year && typeof cs.this_year === "object" ? cs.this_year : null;
      var all = cs.since_first && typeof cs.since_first === "object" ? cs.since_first : null;
      if (!td && !tw && !tm && !ty && !all) return "";
      var todayS = td && td.total_cooldown_s != null && !isNaN(Number(td.total_cooldown_s)) ? Number(td.total_cooldown_s) : 0;
      var evTo = td && td.event_count != null ? Number(td.event_count) : 0;
      /* ~90 min cumulative wait today → full “hot” band */
      var heatIn = Math.min(100, Math.max(0, (todayS / 5400) * 100));
      var hz = heat3(heatIn);
      var cls = "fleet-tile fleet-tile--cooldown-" + hz;
      var weekS = tw && tw.total_cooldown_s != null ? Number(tw.total_cooldown_s) : 0;
      var monthS = tm && tm.total_cooldown_s != null ? Number(tm.total_cooldown_s) : 0;
      var yearS = ty && ty.total_cooldown_s != null ? Number(ty.total_cooldown_s) : 0;
      var allS = all && all.total_cooldown_s != null ? Number(all.total_cooldown_s) : 0;
      var hintParts = [];
      if (tw)
        hintParts.push("Week " + esc(formatCooldownS(weekS)));
      if (tm)
        hintParts.push("Mo " + esc(formatCooldownS(monthS)));
      if (ty)
        hintParts.push("Yr " + esc(formatCooldownS(yearS)));
      if (all)
        hintParts.push("All " + esc(formatCooldownS(allS)));
      var hint = hintParts.length
        ? hintParts.join(" · ")
        : "SQLite · workers’ LLM sleep (not Granite URL)";
      var mem =
        evTo > 0
          ? esc(String(evTo)) + " " + (evTo === 1 ? "wait" : "waits") + " today"
          : "No waits today";
      return (
        '<div class="' +
        cls +
        '">' +
        '<div class="fleet-tile__brand">' +
        tileMark(MARK_COOLDOWN, "LLM throttle waits") +
        '</div><div class="fleet-tile__value fleet-mono">' +
        esc(formatCooldownS(todayS)) +
        '</div><div class="fleet-tile__mem">' +
        mem +
        '</div><div class="fleet-tile__hint">' +
        hint +
        "</div></div>"
      );
    }
