    async function forgeSvcPost(path, okText) {
      setErr("");
      var m = document.getElementById("fleet-svc-action-msg");
      if (m) m.textContent = "…";
      try {
        var res = await fetch(path, {
          method: "POST",
          headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
          body: "{}",
        });
        var j = {};
        try {
          j = await res.json();
        } catch (_e) {
          j = {};
        }
        if (m) {
          if (res.ok && j.ok) m.textContent = okText;
          else m.textContent = "HTTP " + res.status + " — " + esc(String(j.error || j.detail || res.statusText || ""));
        }
      } catch (e) {
        if (m) m.textContent = esc(String(e));
      }
      loadSnapshot().then(function () { scheduleNext(); });
    }
