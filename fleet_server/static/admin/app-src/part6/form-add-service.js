    var addForm = document.getElementById("fleet-add-service-form");
    if (addForm) {
      addForm.addEventListener("submit", async function (ev) {
        ev.preventDefault();
        setErr("");
        var msg = document.getElementById("fleet-add-service-msg");
        if (msg) msg.textContent = "";
        var idEl = document.getElementById("fleet-new-svc-id");
        var rootEl = document.getElementById("fleet-new-svc-root");
        var sid = (idEl && idEl.value ? idEl.value : "").trim().toLowerCase();
        var root = (rootEl && rootEl.value ? rootEl.value : "").trim();
        var overlays = [];
        document.querySelectorAll(".fleet-svc-overlay:checked").forEach(function (c) {
          overlays.push(c.value);
        });
        if (!root) {
          if (msg) msg.textContent = "Enter the Forge LLM directory path (folder with compose.yaml).";
          return;
        }
        var payload = {
          type_id: "forge_llm",
          compose_root: root,
          compose_files: overlays,
        };
        if (sid) {
          payload.id = sid;
        }
        try {
          var res = await fetch("/v1/container-services", {
            method: "POST",
            headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
            body: JSON.stringify(payload),
          });
          var j = {};
          try {
            j = await res.json();
          } catch (_e) {
            j = {};
          }
          if (msg) {
            if (res.ok && j.ok) {
              var createdId = j.service && j.service.id ? String(j.service.id) : sid || "—";
              msg.textContent = "Registered service " + createdId + ".";
            } else {
              msg.textContent = "HTTP " + res.status + " — " + esc(String(j.error || j.detail || ""));
            }
          }
          if (res.ok && j.ok) {
            if (rootEl) rootEl.value = "";
            if (idEl) idEl.value = "";
          }
        } catch (e) {
          if (msg) msg.textContent = esc(String(e));
        }
        loadSnapshot().then(function () { scheduleNext(); });
      });
    }
