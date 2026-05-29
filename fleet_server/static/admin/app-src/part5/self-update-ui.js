    function fleetUpdateUiRefresh() {
      /* Git update affordance lives in #fleet-git-remote-row (checkRemoteAgainstGitHub). */
    }

    function applySelfUpdateMeta(su) {
      __fleetSelfUpdateMeta = su || {};
    }

    function showSystemUpdateModal(commandText) {
      var pre = document.getElementById("fleet-system-update-command");
      var el = document.getElementById("fleet-system-update-modal");
      if (pre) {
        pre.textContent =
          commandText && String(commandText).trim()
            ? String(commandText)
            : "(No command — check FLEET_GIT_ROOT and install-update.sh in the clone.)";
      }
      if (el && typeof bootstrap !== "undefined" && bootstrap.Modal) {
        bootstrap.Modal.getOrCreateInstance(el).show();
      }
    }
