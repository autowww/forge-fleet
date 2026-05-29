    async function openFleetTelemetryHistoryModal() {
      if (__fleetTelHistBusy) return;
      var modalEl = document.getElementById("fleet-tel-history-modal");
      var statusEl = document.getElementById("fleet-tel-hist-status");
      if (!modalEl || typeof bootstrap === "undefined" || !bootstrap.Modal) return;
      __fleetTelHistBusy = true;
      if (statusEl) statusEl.textContent = "Loading…";
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
