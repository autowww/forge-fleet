    async function fetchAdminSnapshot() {
      setErr("");
      var res;
      try {
        var snapPath =
          "/v1/admin/snapshot?jobs_limit=" +
          encodeURIComponent(String(fleetJobsPageSize)) +
          "&jobs_offset=" +
          encodeURIComponent(String(fleetJobsOffset));
        res = await fetch(snapPath, { headers: authHeaders(), cache: "no-store" });
      } catch (e) {
        setErr("Network: " + e);
        return null;
      }
      if (res.status === 401) {
        setErr("Unauthorized — send Authorization: Bearer … matching FLEET_BEARER_TOKEN (or use loopback-only bind).");
        return null;
      }
      if (!res.ok) {
        setErr("HTTP " + res.status);
        return null;
      }
      var data = await res.json();
      if (!data.ok) {
        setErr(JSON.stringify(data));
        return null;
      }
      return data;
    }
