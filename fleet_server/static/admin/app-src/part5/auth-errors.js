    function authHeaders() {
      var t = (localStorage.getItem(LS) || "").trim();
      var h = { Accept: "application/json" };
      if (t) h.Authorization = "Bearer " + t;
      return h;
    }

    function setErr(msg) {
      if (!msg) {
        errEl.classList.add("d-none");
        errEl.textContent = "";
        return;
      }
      errEl.textContent = msg;
      errEl.classList.remove("d-none");
    }
