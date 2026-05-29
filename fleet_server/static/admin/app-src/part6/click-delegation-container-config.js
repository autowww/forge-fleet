    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.getAttribute) return;
      if (t.id === "fleet-type-add-btn") {
        ev.preventDefault();
        openFleetTypeModal("add");
      } else if (t.id === "fleet-types-reload-btn") {
        ev.preventDefault();
        __fleetTypesLoaded = false;
        void loadContainerTypesOnce(true);
      } else if (t.id === "fleet-req-template-add-btn") {
        ev.preventDefault();
        openFleetReqTemplateModal(-1);
      } else if (t.id === "fleet-req-templates-reload-btn") {
        ev.preventDefault();
        void loadRequirementTemplatesOnce(true);
      } else if (t.id === "fleet-req-templates-save-btn") {
        ev.preventDefault();
        void (async function () {
          var msg = document.getElementById("fleet-requirement-templates-editor-msg");
          if (!__fleetReqTemplatesDoc || typeof __fleetReqTemplatesDoc !== "object") {
            if (msg) msg.textContent = "Nothing to save.";
            return;
          }
          try {
            var res = await fetch("/v1/container-templates", {
              method: "PUT",
              headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
              body: JSON.stringify(__fleetReqTemplatesDoc),
            });
            var j = {};
            try {
              j = await res.json();
            } catch (_e) {
              j = {};
            }
            if (msg) msg.textContent = res.ok && j.ok ? "Saved requirement_templates.json." : "HTTP " + res.status + " — " + esc(String(j.error || ""));
            if (res.ok && j.ok) renderFleetReqTemplatesTable(j);
          } catch (e) {
            if (msg) msg.textContent = esc(String(e));
          }
        })();
      } else if (t.closest && t.closest("#fleet-template-build-btn")) {
        ev.preventDefault();
        void (async function () {
          var out = document.getElementById("fleet-template-build-result");
          var inp = document.getElementById("fleet-build-req-ids");
          var raw = (inp && inp.value ? inp.value : "").trim();
          var ids = raw
            ? raw.split(",").map(function (x) {
                return x.trim().toLowerCase();
              }).filter(Boolean)
            : [];
          if (!ids.length) {
            if (out) out.textContent = "Enter at least one requirement slug.";
            return;
          }
          try {
            var res = await fetch("/v1/container-templates/build", {
              method: "POST",
              headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
              body: JSON.stringify({ requirement_ids: ids }),
            });
            var j = {};
            try {
              j = await res.json();
            } catch (_e) {
              j = {};
            }
            if (out) out.textContent = JSON.stringify(j).slice(0, 1200);
          } catch (e) {
            if (out) out.textContent = esc(String(e));
          }
        })();
      } else if (t.classList.contains("fleet-type-edit")) {
        ev.preventDefault();
        var ftid = t.getAttribute("data-type-id");
        if (ftid) openFleetTypeModal("edit", ftid);
      } else if (t.classList.contains("fleet-type-del")) {
        ev.preventDefault();
        var dtid = t.getAttribute("data-type-id");
        if (!dtid || t.disabled) return;
        if (!window.confirm("Delete container type " + dtid + "?")) return;
        void (async function () {
          try {
            var res = await fetch("/v1/container-types/" + encodeURIComponent(dtid), {
              method: "DELETE",
              headers: authHeaders(),
            });
            var j = {};
            try {
              j = await res.json();
            } catch (_e) {
              j = {};
            }
            if (res.ok && j.ok) {
              __fleetTypesLoaded = false;
              await loadContainerTypesOnce(true);
            } else {
              setErr("Delete type: HTTP " + res.status + " — " + esc(String(j.error || ""));
            }
          } catch (e) {
            setErr(esc(String(e)));
          }
        })();
      } else if (t.classList.contains("fleet-req-edit")) {
        ev.preventDefault();
        var ix = parseInt(t.getAttribute("data-req-idx") || "-1", 10);
        if (!isNaN(ix)) openFleetReqTemplateModal(ix);
      } else if (t.classList.contains("fleet-req-del")) {
        ev.preventDefault();
        var ix2 = parseInt(t.getAttribute("data-req-idx") || "-1", 10);
        if (isNaN(ix2) || !__fleetReqTemplatesDoc || !Array.isArray(__fleetReqTemplatesDoc.templates)) return;
        if (!window.confirm("Remove this template row from the editor (save to persist)?")) return;
        __fleetReqTemplatesDoc.templates.splice(ix2, 1);
        renderFleetReqTemplatesTable({ ok: true, version: __fleetReqTemplatesDoc.version, templates: __fleetReqTemplatesDoc.templates });
      }
    });
