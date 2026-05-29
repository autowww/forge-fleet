    function gitShaPrefix7(s) {
      return String(s || "")
        .toLowerCase()
        .replace(/[^a-f0-9]/g, "")
        .slice(0, 7);
    }

    async function checkRemoteAgainstGitHub() {
      var row = document.getElementById("fleet-git-remote-row");
      if (!row) return;
      var localRaw = (__fleetLocalGitSha || "").trim();
      if (!localRaw) {
        row.innerHTML =
          '<span class="opacity-75">No git SHA from server — cannot compare to GitHub.</span>';
        __fleetGitUpdateAvailable = false;
        fleetUpdateUiRefresh();
        return;
      }
      try {
        var res = await fetch("https://api.github.com/repos/" + FLEET_GITHUB_REPO + "/commits/master", {
          headers: { Accept: "application/vnd.github+json" },
        });
        if (!res.ok) {
          row.innerHTML =
            '<span class="opacity-75">GitHub check failed (HTTP ' +
            esc(String(res.status)) +
            ").</span>";
          __fleetGitUpdateAvailable = false;
          fleetUpdateUiRefresh();
          return;
        }
        var j = await res.json();
        var remoteFull = (j.sha || "").trim();
        if (!remoteFull) {
          row.textContent = "";
          __fleetGitUpdateAvailable = false;
          fleetUpdateUiRefresh();
          return;
        }
        var a = gitShaPrefix7(localRaw);
        var b = gitShaPrefix7(remoteFull);
        if (a && b && a === b) {
          row.innerHTML = '<span class="opacity-75">GitHub master matches this host.</span>';
          __fleetGitUpdateAvailable = false;
          fleetUpdateUiRefresh();
          return;
        }
        __fleetGitUpdateAvailable = !!(a && b && a !== b);
        var commitsHref = "https://github.com/" + FLEET_GITHUB_REPO + "/commits/master";
        var profileGh = String((__fleetSelfUpdateMeta || {}).install_profile || "user").toLowerCase();
        if (__fleetSelfUpdateConfigured && profileGh !== "system") {
          row.innerHTML =
            '<span class="text-warning fw-semibold me-1">Update available</span>' +
            '<button type="button" class="btn btn-sm btn-warning" id="fleet-header-git-update-btn">Update Fleet</button>' +
            '<a class="btn btn-sm btn-outline-secondary ms-1" href="' +
            commitsHref +
            '" target="_blank" rel="noopener">GitHub</a>';
        } else if (__fleetSelfUpdateConfigured && profileGh === "system") {
          row.innerHTML =
            '<span class="text-warning fw-semibold me-1">Update available</span>' +
            '<a class="btn btn-sm btn-outline-warning" href="' +
            commitsHref +
            '" target="_blank" rel="noopener">View commits</a>' +
            '<span class="text-body-secondary ms-1 small">System install — update on the host.</span>';
        } else {
          row.innerHTML =
            '<span class="text-warning fw-semibold me-1">Newer commits on GitHub</span>' +
            '<a class="btn btn-sm btn-outline-warning" href="' +
            commitsHref +
            '" target="_blank" rel="noopener">View commits</a>' +
            '<span class="text-body-secondary ms-1" style="font-size:0.72rem">Enable git self-update on Fleet to pull here.</span>';
        }
        fleetUpdateUiRefresh();
      } catch (_e) {
        row.innerHTML = '<span class="opacity-75">Could not reach GitHub.</span>';
        __fleetGitUpdateAvailable = false;
        fleetUpdateUiRefresh();
      }
    }
