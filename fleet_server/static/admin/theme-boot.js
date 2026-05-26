  /* forge-theme.js only registers DOMContentLoaded; if that event already fired, theme + clicks never wire — fix here. */
  (function () {
    function readCookie(name) {
      var m = document.cookie.match(
        new RegExp("(?:^|; )" + name.replace(/[-[\]{}()*+?.\\^$|]/g, "\\$&") + "=([^;]*)")
      );
      return m ? decodeURIComponent(m[1].trim()) : "";
    }
    function syncForgeToggleLabels() {
      var v = readCookie("forge_color_scheme");
      if (v !== "light" && v !== "dark" && v !== "auto") v = "auto";
      var labels = { light: "Light", dark: "Dark", auto: "System" };
      document.querySelectorAll(".forge-theme-dropdown").forEach(function (root) {
        root.setAttribute("data-forge-pref", v);
      });
      document.querySelectorAll("[data-forge-color-scheme]").forEach(function (el) {
        var m = el.getAttribute("data-forge-color-scheme");
        el.classList.toggle("active", m === v);
      });
      document.querySelectorAll(".forge-theme-current").forEach(function (el) {
        el.textContent = labels[v] || "System";
      });
    }
    function applyHtmlThemeFromForge() {
      if (typeof window.forgeGetEffectiveColorScheme === "function") {
        document.documentElement.setAttribute("data-bs-theme", window.forgeGetEffectiveColorScheme());
      }
      syncForgeToggleLabels();
    }
    function wireForgeThemeClicks() {
      if (typeof window.forgeSetColorScheme !== "function") return;
      document.querySelectorAll("[data-forge-color-scheme]").forEach(function (el) {
        el.addEventListener("click", function (ev) {
          ev.preventDefault();
          var m = el.getAttribute("data-forge-color-scheme");
          if (m) window.forgeSetColorScheme(m);
        });
      });
    }
    function bootForgeThemeAdmin() {
      applyHtmlThemeFromForge();
      wireForgeThemeClicks();
      if (window.matchMedia) {
        window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
          var v = readCookie("forge_color_scheme");
          if (v === "auto" || !v) applyHtmlThemeFromForge();
        });
      }
      document.addEventListener("forge-theme-applied", function () {
        syncForgeToggleLabels();
      });
    }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", bootForgeThemeAdmin);
    } else {
      bootForgeThemeAdmin();
    }
  })();