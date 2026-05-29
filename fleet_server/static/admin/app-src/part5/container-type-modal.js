    function openFleetTypeModal(mode, typeId) {
      var err = document.getElementById("fleet-type-edit-err");
      if (err) {
        err.textContent = "";
        err.classList.add("d-none");
      }
      __fleetTypeEditMode = mode;
      var idEl = document.getElementById("fleet-type-field-id");
      var catEl = document.getElementById("fleet-type-field-category");
      var cclEl = document.getElementById("fleet-type-field-cclass");
      var titleEl = document.getElementById("fleet-type-field-title");
      var notesEl = document.getElementById("fleet-type-field-notes");
      var reqEl = document.getElementById("fleet-type-field-req");
      var capA = document.getElementById("fleet-type-cap-admin");
      var capApi = document.getElementById("fleet-type-cap-api");
      var capDr = document.getElementById("fleet-type-cap-docker");
      if (catEl) {
        catEl.innerHTML = "";
        (Array.isArray(__fleetTypesDoc && __fleetTypesDoc.categories) ? __fleetTypesDoc.categories : []).forEach(function (c) {
          if (!c || !c.id) return;
          var o = document.createElement("option");
          o.value = String(c.id);
          o.textContent = String(c.title || c.id);
          catEl.appendChild(o);
        });
      }
      if (mode === "add") {
        if (idEl) {
          idEl.value = "";
          idEl.readOnly = false;
        }
        if (cclEl) cclEl.value = "";
        if (titleEl) titleEl.value = "";
        if (notesEl) notesEl.value = "";
        if (reqEl) reqEl.value = "";
        if (catEl) catEl.value = "job";
        if (capA) capA.checked = false;
        if (capApi) capApi.checked = false;
        if (capDr) capDr.checked = false;
        var h = document.getElementById("fleet-type-edit-hint");
        if (h) h.textContent = "Add a new row to types.json (POST /v1/container-types).";
        var title = document.getElementById("fleet-type-edit-modal-label");
        if (title) title.textContent = "Add container type";
      } else {
        var mat = Array.isArray(__fleetTypesDoc && __fleetTypesDoc.types_materialized)
          ? __fleetTypesDoc.types_materialized
          : [];
        var row = null;
        for (var i = 0; i < mat.length; i++) {
          if (String((mat[i] && mat[i].id) || "") === String(typeId || "")) {
            row = mat[i];
            break;
          }
        }
        if (!row) return;
        if (idEl) {
          idEl.value = String(row.id || "");
          idEl.readOnly = true;
        }
        if (catEl) catEl.value = String(row.category_id || "job");
        if (cclEl) cclEl.value = String(row.container_class || "");
        if (titleEl) titleEl.value = String(row.title || "");
        if (notesEl) notesEl.value = String(row.notes || "");
        if (reqEl) reqEl.value = Array.isArray(row.requirements) ? row.requirements.join(", ") : "";
        var ec = row.effective_capabilities || {};
        if (capA) capA.checked = "admin_spawnable" in row ? !!row.admin_spawnable : !!ec.admin_spawnable;
        if (capApi) capApi.checked = "api_manage_services" in row ? !!row.api_manage_services : !!ec.api_manage_services;
        if (capDr) capDr.checked = "allow_docker_argv_jobs" in row ? !!row.allow_docker_argv_jobs : !!ec.allow_docker_argv_jobs;
        var h2 = document.getElementById("fleet-type-edit-hint");
        if (h2) h2.textContent = "Update this row (PUT /v1/container-types/{id}).";
        var title2 = document.getElementById("fleet-type-edit-modal-label");
        if (title2) title2.textContent = "Edit container type";
      }
      var modalEl = document.getElementById("fleet-type-edit-modal");
      if (modalEl && typeof bootstrap !== "undefined" && bootstrap.Modal) {
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    }
