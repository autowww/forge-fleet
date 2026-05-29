    async function loadContainerTypesOnce(force) {
      if (__fleetTypesLoaded && !force) return;
      try {
        var res = await fetch("/v1/container-types", { headers: authHeaders(), cache: "no-store" });
        if (!res.ok) return;
        var doc = await res.json();
        if (!doc.ok || !Array.isArray(doc.types)) return;
        __fleetTypesDoc = doc;
        __fleetTypesLoaded = true;
        var wrap = document.getElementById("fleet-container-types-wrap");
        var tbl = document.getElementById("fleet-container-types-table");
        if (!wrap || !tbl) return;
        wrap.classList.remove("d-none");
        var mat = Array.isArray(doc.types_materialized) ? doc.types_materialized : [];
        function effCaps(t) {
          var e = t && t.effective_capabilities;
          return e && typeof e === "object" ? e : {};
        }
        var head =
          '<div class="table-responsive"><table class="table table-sm table-bordered mb-0 fleet-mono"><thead><tr>' +
          "<th>id</th><th>category</th><th>container_class</th><th>requirements</th><th>telemetry</th><th class=\"text-end\">actions</th></tr></thead><tbody>";
        var body = mat
          .map(function (t) {
            var tid = String((t && t.id) || "");
            var cid = String((t && t.category_id) || "");
            var cclass = String((t && t.container_class) || "");
            var reqs = Array.isArray(t.requirements) ? t.requirements.join(", ") : "";
            var ec = effCaps(t);
            var caps =
              "adm " +
              (ec.admin_spawnable ? "Y" : "n") +
              " · svc " +
              (ec.api_manage_services ? "Y" : "n") +
              " · dock " +
              (ec.allow_docker_argv_jobs ? "Y" : "n");
            return (
              "<tr class=\"fleet-type-card\" data-fleet-type-id=\"" +
              esc(tid) +
              "\" data-category-id=\"" +
              esc(cid) +
              "\" data-container-class=\"" +
              esc(cclass) +
              "\"><td>" +
              esc(tid) +
              "</td><td>" +
              esc(cid) +
              "</td><td>" +
              esc(cclass) +
              "</td><td class=\"small\">" +
              esc(reqs) +
              "</td><td class=\"small\"><span data-fleet-type-tel>—</span><div class=\"text-body-secondary\">" +
              esc(caps) +
              "</div></td><td class=\"text-nowrap text-end\"><button type=\"button\" class=\"btn btn-sm btn-outline-primary me-1 fleet-type-edit\" data-type-id=\"" +
              esc(tid) +
              "\">Edit</button><button type=\"button\" class=\"btn btn-sm btn-outline-danger fleet-type-del\" data-type-id=\"" +
              esc(tid) +
              "\"" +
              (tid === "empty" ? " disabled" : "") +
              ">Delete</button></td></tr>"
            );
          })
          .join("");
        tbl.innerHTML =
          head +
          body +
          (mat.length ? "" : '<tr><td colspan="6" class="text-body-secondary">No types.</td></tr>') +
          "</tbody></table></div>";
        refreshContainerTypesTelemetry(__fleetLastOrchestration);
        await loadRequirementTemplatesOnce(force);
      } catch (_e) {
        /* ignore */
      }
    }
