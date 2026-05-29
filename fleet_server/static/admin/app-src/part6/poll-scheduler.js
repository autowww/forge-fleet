    function scheduleNext() {
      nextFire = Date.now() + POLL_MS;
    }

    function tick() {
      var ms = Math.max(0, nextFire - Date.now());
      if (ms <= 0) {
        loadSnapshot().then(function () { scheduleNext(); });
      }
    }
