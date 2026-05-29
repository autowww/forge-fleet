    function renderManagedServices(integ) {
      var wrap = document.getElementById("fleet-managed-services-wrap");
      var pathsEl = document.getElementById("fleet-config-paths");
      var rowsEl = document.getElementById("fleet-managed-services-rows");
      var msgEl = document.getElementById("fleet-svc-action-msg");
      if (!wrap || !pathsEl || !rowsEl) return;
      var cl = integ.container_layout;
      if (!cl) {
        wrap.classList.add("d-none");
        return;
      }
      wrap.classList.remove("d-none");
      pathsEl.textContent =
        "types_file=" +
        cl.types_file +
        " · services_dir=" +
        cl.services_dir +
        (cl.requirement_templates_file ? " · req_templates=" + cl.requirement_templates_file : "") +
        (cl.build_cache_file ? " · build_cache=" + cl.build_cache_file : "");
      if (msgEl) msgEl.textContent = "";
      var svcs = integ.forge_llm_services || [];
      if (!svcs.length) {
        rowsEl.innerHTML =
          "<p class=\"text-body-secondary mb-0\">No <code class=\"fleet-mono\">forge_llm</code> services yet. Use <strong>Register stack</strong> below, or set <code class=\"fleet-mono\">FLEET_FORGE_LLM_ROOT</code> and restart Fleet once to auto-create <code class=\"fleet-mono\">default.json</code>.</p>";
        return;
      }
      var head =
        "<div class=\"table-responsive\"><table class=\"table table-sm table-bordered mb-0 fleet-mono\"><thead><tr>" +
        "<th>id</th><th>label</th><th>compose</th><th>status</th><th></th></tr></thead><tbody>";
      var body = svcs
        .map(function (s) {
          var st = (s.services_running != null ? s.services_running : "—") + " / " + (s.services_total != null ? s.services_total : "—") + " running";
          if (s.ps_ok === false) st += " · ps failed";
          var root = String(s.compose_root || "").slice(0, 48) + (String(s.compose_root || "").length > 48 ? "…" : "");
          var cf = (s.compose_files || []).join(", ") || "compose.yaml";
          var sid = String(s.id || "");
          return (
            "<tr><td>" +
            esc(sid) +
            "</td><td>" +
            esc(s.label || "") +
            "</td><td title=\"" +
            esc(String(s.compose_root || "")) +
            "\">" +
            esc(root) +
            "<div class=\"small text-body-secondary\">" +
            esc(cf) +
            "</div></td><td>" +
            esc(st) +
            "</td><td class=\"text-nowrap\"><button type=\"button\" class=\"btn btn-sm btn-outline-success me-1 fleet-svc-start\" data-svc-id=\"" +
            esc(sid) +
            "\">Start</button><button type=\"button\" class=\"btn btn-sm btn-outline-warning fleet-svc-stop\" data-svc-id=\"" +
            esc(sid) +
            "\">Stop</button></td></tr>"
          );
        })
        .join("");
      rowsEl.innerHTML = head + body + "</tbody></table></div>";
    }
