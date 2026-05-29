    function renderFleetJobDetailPayload(j) {
      if (!j || !j.ok) {
        return "<p class=\"text-danger mb-0\">Could not load job.</p>";
      }
      var oid = jobOutcomeHuman(j);
      var parts = [];
      parts.push("<dl class=\"row mb-3 small\">");
      parts.push("<dt class=\"col-sm-3 text-body-secondary\">Status</dt><dd class=\"col-sm-9\">" + statusPill(j.status) + "</dd>");
      parts.push(
        "<dt class=\"col-sm-3 text-body-secondary\">Outcome</dt><dd class=\"col-sm-9\"><span class=\"" +
          oid.cls +
          "\">" +
          esc(oid.text) +
          "</span></dd>"
      );
      parts.push(
        "<dt class=\"col-sm-3 text-body-secondary\">Job ID</dt><dd class=\"col-sm-9\"><code class=\"fleet-mono user-select-all\">" +
          esc(j.id || "") +
          "</code></dd>"
      );
      if (j.session_id)
        parts.push(
          "<dt class=\"col-sm-3 text-body-secondary\">Session</dt><dd class=\"col-sm-9\"><code class=\"fleet-mono user-select-all\">" +
            esc(j.session_id) +
            "</code></dd>"
        );
      if (j.kind) parts.push("<dt class=\"col-sm-3 text-body-secondary\">Kind</dt><dd class=\"col-sm-9\">" + esc(j.kind) + "</dd>");
      if (j.container_id)
        parts.push(
          "<dt class=\"col-sm-3 text-body-secondary\">Container</dt><dd class=\"col-sm-9\"><code class=\"fleet-mono\">" +
            esc(j.container_id) +
            "</code></dd>"
        );
      if (j.created != null)
        parts.push("<dt class=\"col-sm-3 text-body-secondary\">Created</dt><dd class=\"col-sm-9\">" + esc(fmtTime(j.created)) + "</dd>");
      if (j.updated != null)
        parts.push("<dt class=\"col-sm-3 text-body-secondary\">Updated</dt><dd class=\"col-sm-9\">" + esc(fmtTime(j.updated)) + "</dd>");
      parts.push("</dl>");
      var meta = j.meta && typeof j.meta === "object" ? j.meta : {};
      if (Object.keys(meta).length) {
        parts.push("<h6 class=\"text-body-secondary text-uppercase small mb-2\">Meta (JSON)</h6>");
        parts.push(
          "<pre class=\"fleet-mono small bg-body-secondary border rounded p-2 mb-3\" style=\"max-height:12rem;overflow:auto\">" +
            esc(JSON.stringify(meta, null, 2)) +
            "</pre>"
        );
      }
      if (j.argv && j.argv.length) {
        parts.push("<h6 class=\"text-body-secondary text-uppercase small mb-2\">Docker command</h6>");
        parts.push(
          "<pre class=\"fleet-mono small bg-body-secondary border rounded p-2 mb-3\" style=\"max-height:14rem;overflow:auto;white-space:pre-wrap\">" +
            esc(fleetJobArgvShell(j.argv)) +
            "</pre>"
        );
      }
      var out = (j.stdout || "").trim();
      var err = (j.stderr || "").trim();
      if (out) {
        parts.push("<h6 class=\"text-body-secondary text-uppercase small mb-2\">Stdout</h6>");
        parts.push(
          "<pre class=\"fleet-mono small bg-body-secondary border rounded p-2 mb-3\" style=\"max-height:14rem;overflow:auto;white-space:pre-wrap\">" +
            esc(out.length > 120000 ? out.slice(0, 120000) + "\n… truncated" : out) +
            "</pre>"
        );
      }
      if (err) {
        parts.push("<h6 class=\"text-body-secondary text-uppercase small mb-2\">Stderr</h6>");
        parts.push(
          "<pre class=\"fleet-mono small bg-danger-subtle border border-danger-subtle rounded p-2 mb-0\" style=\"max-height:14rem;overflow:auto;white-space:pre-wrap\">" +
            esc(err.length > 120000 ? err.slice(0, 120000) + "\n… truncated" : err) +
            "</pre>"
        );
      }
      return parts.join("");
    }

    async function openFleetJobDetail(jobId) {
      var el = document.getElementById("fleet-job-detail-modal");
      var body = document.getElementById("fleet-job-detail-body");
      if (!el || !body) return;
      body.innerHTML = "<p class=\"text-body-secondary mb-0\">Loading…</p>";
      if (typeof bootstrap !== "undefined" && bootstrap.Modal) {
        bootstrap.Modal.getOrCreateInstance(el).show();
      }
      try {
        var res = await fetch("/v1/jobs/" + encodeURIComponent(jobId), { headers: authHeaders(), cache: "no-store" });
        var j = {};
        try {
          j = await res.json();
        } catch (_e) {
          j = {};
        }
        if (!res.ok) {
          body.innerHTML =
            "<p class=\"text-danger mb-0\">HTTP " +
            res.status +
            " — " +
            esc(String(j.error || res.statusText || "error")) +
            "</p>";
          return;
        }
        body.innerHTML = renderFleetJobDetailPayload(j);
      } catch (e) {
        body.innerHTML = "<p class=\"text-danger mb-0\">" + esc(String(e)) + "</p>";
      }
    }
