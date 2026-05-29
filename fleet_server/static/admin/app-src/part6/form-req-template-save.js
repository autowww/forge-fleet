    var fleetReqSaveBtn = document.getElementById("fleet-req-edit-save");
    if (fleetReqSaveBtn) {
      fleetReqSaveBtn.addEventListener("click", function () {
        var err = document.getElementById("fleet-req-edit-err");
        if (err) {
          err.textContent = "";
          err.classList.add("d-none");
        }
        var idEl = document.getElementById("fleet-req-field-id");
        var titleEl = document.getElementById("fleet-req-field-title");
        var kindEl = document.getElementById("fleet-req-field-kind");
        var refEl = document.getElementById("fleet-req-field-ref");
        var notesEl = document.getElementById("fleet-req-field-notes");
        var row = {
          id: (idEl && idEl.value ? idEl.value : "").trim().toLowerCase(),
          title: (titleEl && titleEl.value ? titleEl.value : "").trim(),
          kind: kindEl ? kindEl.value : "dockerfile",
          ref: (refEl && refEl.value ? refEl.value : "").trim(),
          notes: notesEl && notesEl.value ? notesEl.value : "",
        };
        if (!row.id) {
          if (err) {
            err.textContent = "Template id is required.";
            err.classList.remove("d-none");
          }
          return;
        }
        var templates = __fleetReqTemplatesDoc && Array.isArray(__fleetReqTemplatesDoc.templates)
          ? __fleetReqTemplatesDoc.templates.slice()
          : [];
        if (__fleetReqEditIdx >= 0 && __fleetReqEditIdx < templates.length) {
          templates[__fleetReqEditIdx] = row;
        } else {
          var dup = false;
          for (var i = 0; i < templates.length; i++) {
            if (String((templates[i] && templates[i].id) || "") === row.id) {
              dup = true;
              templates[i] = row;
              break;
            }
          }
          if (!dup) templates.push(row);
        }
        var ver = __fleetReqTemplatesDoc && __fleetReqTemplatesDoc.version != null ? __fleetReqTemplatesDoc.version : 1;
        renderFleetReqTemplatesTable({ ok: true, version: ver, templates: templates });
        var modalEl = document.getElementById("fleet-req-template-modal");
        if (modalEl && typeof bootstrap !== "undefined" && bootstrap.Modal) {
          var mi = bootstrap.Modal.getInstance(modalEl);
          if (mi) mi.hide();
          else bootstrap.Modal.getOrCreateInstance(modalEl).hide();
        }
      });
    }
