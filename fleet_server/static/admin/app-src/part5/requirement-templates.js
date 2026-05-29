    function renderFleetReqTemplatesTable(doc) {
      if (!doc || !doc.ok) return;
      __fleetReqTemplatesDoc = doc;
      var tbl = document.getElementById("fleet-requirement-templates-table");
      if (!tbl) return;
      var templates = Array.isArray(doc.templates) ? doc.templates : [];
      var head =
        '<div class="table-responsive"><table class="table table-sm table-bordered mb-0 fleet-mono"><thead><tr>' +
        "<th>id</th><th>kind</th><th>ref</th><th>title</th><th class=\"text-end\">actions</th></tr></thead><tbody>";
      var body = templates
        .map(function (row, idx) {
          var rid = esc(String((row && row.id) || ""));
          return (
            "<tr><td>" +
            rid +
            "</td><td>" +
            esc(String((row && row.kind) || "")) +
            "</td><td class=\"small\" title=\"" +
            esc(String((row && row.ref) || "")) +
            "\">" +
            esc(String((row && row.ref) || "").slice(0, 72)) +
            (String((row && row.ref) || "").length > 72 ? "…" : "") +
            "</td><td class=\"small\">" +
            esc(String((row && row.title) || "")) +
            "</td><td class=\"text-end text-nowrap\"><button type=\"button\" class=\"btn btn-sm btn-outline-primary fleet-req-edit\" data-req-idx=\"" +
            idx +
            "\">Edit</button> <button type=\"button\" class=\"btn btn-sm btn-outline-danger fleet-req-del\" data-req-idx=\"" +
            idx +
            "\">Remove</button></td></tr>"
          );
        })
        .join("");
      tbl.innerHTML =
        head +
        body +
        (templates.length ? "" : '<tr><td colspan="5" class="text-body-secondary">No templates yet.</td></tr>') +
        "</tbody></table></div>";
    }

    async function loadRequirementTemplatesOnce(force) {
      try {
        var res = await fetch("/v1/container-templates", { headers: authHeaders(), cache: "no-store" });
        if (!res.ok) return;
        var doc = await res.json();
        renderFleetReqTemplatesTable(doc);
      } catch (_e) {
        /* ignore */
      }
    }
