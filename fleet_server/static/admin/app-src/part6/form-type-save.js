    var fleetTypeSaveBtn = document.getElementById("fleet-type-edit-save");
    if (fleetTypeSaveBtn) {
      fleetTypeSaveBtn.addEventListener("click", async function () {
        var err = document.getElementById("fleet-type-edit-err");
        if (err) {
          err.textContent = "";
          err.classList.add("d-none");
        }
        var idEl = document.getElementById("fleet-type-field-id");
        var catEl = document.getElementById("fleet-type-field-category");
        var cclEl = document.getElementById("fleet-type-field-cclass");
        var titleEl = document.getElementById("fleet-type-field-title");
        var notesEl = document.getElementById("fleet-type-field-notes");
        var reqEl = document.getElementById("fleet-type-field-req");
        var capA = document.getElementById("fleet-type-cap-admin");
        var capApi = document.getElementById("fleet-type-cap-api");
        var capDr = document.getElementById("fleet-type-cap-docker");
        var payload = {
          id: (idEl && idEl.value ? idEl.value : "").trim().toLowerCase(),
          category_id: catEl ? catEl.value : "job",
          container_class: (cclEl && cclEl.value ? cclEl.value : "").trim().toLowerCase(),
          title: (titleEl && titleEl.value ? titleEl.value : "").trim(),
          notes: notesEl && notesEl.value ? notesEl.value : "",
        };
        var rq = (reqEl && reqEl.value ? reqEl.value : "")
          .split(",")
          .map(function (x) {
            return x.trim().toLowerCase();
          })
          .filter(Boolean);
        if (rq.length) payload.requirements = rq;
        if (capA && capA.checked) payload.admin_spawnable = true;
        else payload.admin_spawnable = false;
        if (capApi && capApi.checked) payload.api_manage_services = true;
        else payload.api_manage_services = false;
        if (capDr && capDr.checked) payload.allow_docker_argv_jobs = true;
        else payload.allow_docker_argv_jobs = false;
        try {
          var url =
            __fleetTypeEditMode === "add"
              ? "/v1/container-types"
              : "/v1/container-types/" + encodeURIComponent(payload.id);
          var method = __fleetTypeEditMode === "add" ? "POST" : "PUT";
          var res = await fetch(url, {
            method: method,
            headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
            body: JSON.stringify(payload),
          });
          var j = {};
          try {
            j = await res.json();
          } catch (_e) {
            j = {};
          }
          if (!res.ok || !j.ok) {
            if (err) {
              err.textContent = esc(String(j.error || j.detail || res.status));
              err.classList.remove("d-none");
            }
            return;
          }
          var modalEl = document.getElementById("fleet-type-edit-modal");
          if (modalEl && typeof bootstrap !== "undefined" && bootstrap.Modal) {
            var mi = bootstrap.Modal.getInstance(modalEl);
            if (mi) mi.hide();
            else bootstrap.Modal.getOrCreateInstance(modalEl).hide();
          }
          __fleetTypesLoaded = false;
          await loadContainerTypesOnce(true);
        } catch (e) {
          if (err) {
            err.textContent = esc(String(e));
            err.classList.remove("d-none");
          }
        }
      });
    }
