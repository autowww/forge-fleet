    function fmtWatts(w) {
      if (w == null || isNaN(Number(w)) || Number(w) < 0) return "—";
      return String(Math.round(Number(w)));
    }

    function formatLedgerKwhLine(ledger) {
      if (!ledger || ledger.total_kwh == null || isNaN(Number(ledger.total_kwh))) {
        return "No running total yet — leave this page open a little while and it may appear.";
      }
      var t = Number(ledger.total_kwh);
      var s = t < 1 ? String(Math.round(t * 1000)) + " Wh" : String(Math.round(t)) + " kWh";
      return "Electricity use logged while Fleet was watching: " + esc(s) + ".";
    }

    function formatLedgerKwhShort(ledger) {
      if (!ledger || ledger.total_kwh == null || isNaN(Number(ledger.total_kwh))) {
        return "";
      }
      var t = Number(ledger.total_kwh);
      var s = t < 1 ? String(Math.round(t * 1000)) + " Wh" : String(Math.round(t)) + " kWh";
      return "Running total: " + esc(s) + ".";
    }
