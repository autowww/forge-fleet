    function orchestrationScalars(orch) {
      if (!orch || typeof orch !== "object") return { managed: 0, jobs: 0 };
      var bt = orch.by_type_id;
      var managed = 0;
      if (bt && bt.forge_llm && bt.forge_llm.services_running != null) {
        managed = Number(bt.forge_llm.services_running) || 0;
      }
      var jb = orch.job_running_by_container_class || {};
      var jobs = 0;
      Object.keys(jb).forEach(function (k) {
        jobs += Number(jb[k]) || 0;
      });
      return { managed: managed, jobs: jobs };
    }
