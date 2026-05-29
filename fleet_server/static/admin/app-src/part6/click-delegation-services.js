    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.getAttribute) return;
      if (t.classList.contains("fleet-svc-start")) {
        var sid = t.getAttribute("data-svc-id");
        if (sid) forgeSvcPost("/v1/container-services/" + encodeURIComponent(sid) + "/start", "start sent for " + sid);
      } else if (t.classList.contains("fleet-svc-stop")) {
        var sid2 = t.getAttribute("data-svc-id");
        if (sid2) forgeSvcPost("/v1/container-services/" + encodeURIComponent(sid2) + "/stop", "stop sent for " + sid2);
      }
    });
