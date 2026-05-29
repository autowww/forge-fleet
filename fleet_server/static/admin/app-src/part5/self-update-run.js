    function formatSelfUpdateSteps(steps) {
      if (!Array.isArray(steps) || !steps.length) return "";
      return steps
        .map(function (s) {
          var out = (s.stdout || "").trim();
          var err = (s.stderr || "").trim();
          var body = (out + (out && err ? "\n" : "") + err).trim();
          return (
            "— " +
            esc(s.step || "") +
            " (exit " +
            esc(String(s.returncode != null ? s.returncode : "?")) +
            ")\n" +
            esc(body).slice(0, 12000)
          );
        })
        .join("\n\n");
    }

    async function waitFleetBack(maxMs) {
      var deadline = Date.now() + maxMs;
      while (Date.now() < deadline) {
        try {
          var res = await fetch("/v1/version", { headers: authHeaders(), cache: "no-store" });
          if (res.ok) return true;
        } catch (_e) {
          /* server restarting */
        }
        await new Promise(function (r) {
          setTimeout(r, 400);
        });
      }
      return false;
    }

    async function doGitSelfUpdate() {
      var st = document.getElementById("fleet-self-update-status");
      var logEl = document.getElementById("fleet-self-update-log");
      if (!__fleetSelfUpdateConfigured) {
        setErr(
          "Git self-update is not configured. Set FLEET_GIT_ROOT to your forge-fleet checkout (with .git), or run this Fleet process from that clone."
        );
        return;
      }
      var su = __fleetSelfUpdateMeta || {};
      if (String(su.install_profile || "user").toLowerCase() === "system") {
        return;
      }
      setErr("");
      if (st) st.textContent = "Running git pull…";
      if (logEl) {
        logEl.textContent = "";
        logEl.classList.add("d-none");
      }
      try {
        var res = await fetch("/v1/admin/git-self-update", {
          method: "POST",
          headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
          body: "{}",
        });
        var j = {};
        try {
          j = await res.json();
        } catch (_e) {
          j = {};
        }
        if (logEl && j.steps) {
          logEl.textContent = formatSelfUpdateSteps(j.steps);
          logEl.classList.remove("d-none");
        }
        if (!res.ok || !j.ok) {
          if (st) st.textContent = "Failed (" + res.status + ").";
          setErr(String(j.detail || j.error || "git-self-update failed"));
          return;
        }
        if (st) st.textContent = j.note || "OK.";
        if (j.scheduled_restart) {
          if (st) st.textContent = (j.note || "") + " Waiting for Fleet to come back…";
          await new Promise(function (r) {
            setTimeout(r, j.reload_after_ms || 2200);
          });
          var ok = await waitFleetBack(45000);
          if (st) st.textContent = ok ? "Reloading…" : "Fleet did not respond in time — reload manually.";
          if (ok) window.location.reload();
        }
      } catch (e) {
        setErr(String(e));
        if (st) st.textContent = "";
      }
    }
