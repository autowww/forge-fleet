    function openFleetReqTemplateModal(idx) {
      var err = document.getElementById("fleet-req-edit-err");
      if (err) {
        err.textContent = "";
        err.classList.add("d-none");
      }
      __fleetReqEditIdx = typeof idx === "number" ? idx : -1;
      var templates = __fleetReqTemplatesDoc && Array.isArray(__fleetReqTemplatesDoc.templates)
        ? __fleetReqTemplatesDoc.templates
        : [];
      var row = __fleetReqEditIdx >= 0 ? templates[__fleetReqEditIdx] : null;
      var idEl = document.getElementById("fleet-req-field-id");
      var titleEl = document.getElementById("fleet-req-field-title");
      var kindEl = document.getElementById("fleet-req-field-kind");
      var refEl = document.getElementById("fleet-req-field-ref");
      var notesEl = document.getElementById("fleet-req-field-notes");
      if (row && typeof row === "object") {
        if (idEl) {
          idEl.value = String(row.id || "");
          idEl.readOnly = true;
        }
        if (titleEl) titleEl.value = String(row.title || "");
        if (kindEl) kindEl.value = String(row.kind || "dockerfile");
        if (refEl) refEl.value = String(row.ref || "");
        if (notesEl) notesEl.value = String(row.notes || "");
      } else {
        if (idEl) {
          idEl.value = "";
          idEl.readOnly = false;
        }
        if (titleEl) titleEl.value = "";
        if (kindEl) kindEl.value = "dockerfile";
        if (refEl) refEl.value = "";
        if (notesEl) notesEl.value = "";
      }
      var modalEl = document.getElementById("fleet-req-template-modal");
      if (modalEl && typeof bootstrap !== "undefined" && bootstrap.Modal) {
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    }
