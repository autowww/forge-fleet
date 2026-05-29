    function statusPill(st) {
      var c = "fleet-pill st-" + String(st || "").toLowerCase();
      return '<span class="' + c + '">' + esc(st || "?") + "</span>";
    }

    /** Human-readable job outcome for tables and detail header. */
    function jobOutcomeHuman(j) {
      var st = String(j.status || "").toLowerCase();
      var ex = j.exit_code;
      if (st === "queued") return { cls: "text-body-secondary", text: "Queued" };
      if (st === "running") return { cls: "text-warning", text: "Running…" };
      if (st === "cancelled") return { cls: "text-body-secondary", text: "Cancelled" };
      if (st === "failed") {
        if (ex != null && ex !== "") return { cls: "text-danger", text: "Failed · exit " + ex };
        return { cls: "text-danger", text: "Failed" };
      }
      if (st === "completed") {
        if (ex === 0 || ex === "0") return { cls: "text-success", text: "Succeeded" };
        if (ex != null && ex !== "") return { cls: "text-danger", text: "Finished · exit " + ex };
        return { cls: "text-success", text: "Finished" };
      }
      return { cls: "text-body-secondary", text: String(j.status || "—") };
    }

    function fleetJobArgvShell(argv) {
      if (!argv || !argv.length) return "";
      return argv
        .map(function (x) {
          var s = String(x);
          if (/[\s'"\\]/.test(s)) return "'" + s.replace(/'/g, "'\\''") + "'";
          return s;
        })
        .join(" ");
    }
