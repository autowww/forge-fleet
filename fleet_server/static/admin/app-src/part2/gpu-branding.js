    var GPU_LOGO_BASE = "/admin/static/gpu-logos/";
    function gpuLogoImg(vendor, alt, extraClass) {
      var c = "fleet-gpu-logo" + (extraClass ? " " + extraClass : "");
      return (
        '<img class="' +
        c +
        '" src="' +
        esc(GPU_LOGO_BASE + vendor + ".png") +
        '" alt="' +
        esc(alt) +
        '" loading="lazy" width="100" height="32" />'
      );
    }
    function gpuLogoButton(vendor, alt, stub) {
      var intel = vendor === "intel";
      var cls = "fleet-gpu-logo-btn" + (stub ? " fleet-gpu-logo-btn--stub" : "") + (intel ? " fleet-gpu-logo-btn--intel" : "");
      return (
        '<span class="' +
        cls +
        '">' +
        gpuLogoImg(vendor, alt, "fleet-gpu-logo--inbtn") +
        '<span class="visually-hidden">' +
        esc(alt) +
        "</span></span>"
      );
    }
    function gpuLogoBrand(vendor, alt) {
      return '<div class="fleet-gpu-brand">' + gpuLogoButton(vendor, alt, false) + "</div>";
    }
    function renderGpuStubTile() {
      return "";
    }
