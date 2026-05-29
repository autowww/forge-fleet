    function formatCooldownS(sec) {
      var s = sec != null && !isNaN(Number(sec)) ? Number(sec) : 0;
      if (s <= 0) return "0s";
      if (s < 60) return Math.round(s * 10) / 10 + "s";
      var m = Math.floor(s / 60);
      var r = s - m * 60;
      if (s < 3600) {
        return m + "m" + (r >= 0.5 ? " " + Math.round(r) + "s" : "");
      }
      var h = Math.floor(s / 3600);
      var s2 = s - h * 3600;
      var m2 = Math.floor(s2 / 60);
      return h + "h" + (m2 ? " " + m2 + "m" : "");
    }
