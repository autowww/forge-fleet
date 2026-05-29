    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.getAttribute) return;
      if (t.id === "fleet-header-git-update-btn" || (t.closest && t.closest("#fleet-header-git-update-btn"))) {
        ev.preventDefault();
        doGitSelfUpdate();
      } else if (t.classList && t.classList.contains("fleet-power-open-diag")) {
        ev.preventDefault();
        openFleetPowerDiagModal();
      }
    });
