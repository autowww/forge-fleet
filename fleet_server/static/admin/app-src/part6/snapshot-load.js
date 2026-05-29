    async function loadSnapshot() {
      var data = await fetchAdminSnapshot();
      if (!data) return false;
      return applySnapshotData(data);
    }
