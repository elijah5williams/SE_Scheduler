/*
  Phone-app behavior. Most of it only runs in the installed app (html.is-app):
  tab bar "+" menu, pull to refresh, the number on the app icon, saving the schedule for
  offline use, "new version" notice, notifications switch, and clearing saved data on log out.
  In a phone browser tab it only shows the "Get the app" banner.
*/
(function () {
  "use strict";

  var root = document.documentElement;
  var isApp = root.classList.contains("is-app");
  var script = document.currentScript || document.querySelector("script[data-status-url]");
  var cfg = script ? script.dataset : {};
  var signedIn = cfg.signedIn === "1";
  var PRIVATE_CACHE = "athlete-planner-private";

  function store(method, key, value) {
    try { return window.localStorage[method](key, value); } catch (e) { return null; }
  }

  function csrfToken() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (input) return input.value;
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(body || {}),
    });
  }

  /* ---------- Toast ---------- */
  var toast = document.querySelector(".app-toast");
  var toastTimer;
  function showToast(text, actionLabel, onAction, stay) {
    if (!toast) return;
    toast.querySelector("[data-toast-text]").textContent = text;
    var button = toast.querySelector("[data-toast-action]");
    button.hidden = !actionLabel;
    button.textContent = actionLabel || "";
    button.onclick = onAction || null;
    toast.hidden = false;
    clearTimeout(toastTimer);
    if (!stay) toastTimer = setTimeout(function () { toast.hidden = true; }, 5000);
  }

  /* ---------- "+" sheet ---------- */
  var sheet = document.getElementById("appAddSheet");
  var backdrop = document.querySelector(".app-sheet-backdrop");
  var opener = document.querySelector("[data-sheet-open]");
  function setSheet(open) {
    if (!sheet) return;
    sheet.classList.toggle("open", open);
    backdrop.classList.toggle("open", open);
    if (open) {
      var first = sheet.querySelector("a");
      if (first) first.focus();
    } else if (opener) {
      opener.focus();
    }
  }
  if (opener) opener.addEventListener("click", function () { setSheet(true); });
  if (backdrop) backdrop.addEventListener("click", function () { setSheet(false); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && sheet && sheet.classList.contains("open")) setSheet(false);
  });

  /* ---------- Pull to refresh (installed apps on iPhone don't have it) ---------- */
  var ptr = document.querySelector(".app-ptr");
  if (isApp && ptr) {
    var startY = null, pull = 0, THRESHOLD = 75;
    window.addEventListener("touchstart", function (e) {
      startY = window.scrollY <= 0 && e.touches.length === 1 && !(sheet && sheet.classList.contains("open")) ? e.touches[0].clientY : null;
      pull = 0;
    }, { passive: true });
    window.addEventListener("touchmove", function (e) {
      if (startY === null) return;
      pull = Math.max(0, e.touches[0].clientY - startY);
      if (pull <= 0) return;
      var shown = Math.min(pull, 120);
      ptr.style.opacity = String(Math.min(1, shown / THRESHOLD));
      ptr.style.transform = "translateY(" + (shown * 0.6 - 10) + "px)";
      ptr.classList.toggle("ready", pull > THRESHOLD);
    }, { passive: true });
    window.addEventListener("touchend", function () {
      if (startY === null) return;
      startY = null;
      if (pull > THRESHOLD) {
        ptr.classList.remove("ready");
        ptr.classList.add("loading");
        ptr.style.transform = "translateY(40px)";
        window.location.reload();
      } else {
        ptr.style.opacity = "0";
        ptr.style.transform = "";
      }
    });
  }

  /* ---------- Number on the app icon + "Today" tab ---------- */
  function refreshBadge() {
    if (!isApp || !signedIn || !cfg.statusUrl) return;
    fetch(cfg.statusUrl, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        var n = data.badge || 0;
        if (navigator.setAppBadge) {
          (n ? navigator.setAppBadge(n) : navigator.clearAppBadge()).catch(function () {});
        }
        var dot = document.querySelector("[data-app-badge]");
        if (dot) {
          dot.textContent = n > 9 ? "9+" : String(n);
          dot.hidden = !n;
          dot.setAttribute("aria-label", n + " left today");
        }
      })
      .catch(function () {});
  }

  /* ---------- Save the next two weeks for offline use ---------- */
  function saveOffline() {
    // The service worker stores the response in the phone's app cache (see sw.js).
    if (!isApp || !signedIn || !cfg.offlineUrl || !navigator.onLine) return;
    fetch(cfg.offlineUrl, { credentials: "same-origin", headers: { "X-App-Save": "1" } }).catch(function () {});
  }

  if (isApp && signedIn) {
    refreshBadge();
    saveOffline();
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") { refreshBadge(); saveOffline(); }
    });
  }

  window.addEventListener("offline", function () {
    if (isApp) showToast("You're offline. Your saved schedule is still available.");
  });
  window.addEventListener("online", function () {
    if (isApp) showToast("Back online.", "Refresh", function () { window.location.reload(); });
  });

  /* ---------- New version ready ---------- */
  if ("serviceWorker" in navigator && navigator.serviceWorker.controller) {
    navigator.serviceWorker.addEventListener("controllerchange", function () {
      showToast("A new version of the app is ready.", "Update", function () { window.location.reload(); }, true);
    });
  }

  /* ---------- Log out: remove saved schedule and this phone's notifications first ---------- */
  function clearDeviceData() {
    var jobs = [];
    if (window.caches) jobs.push(caches.delete(PRIVATE_CACHE));
    if (navigator.clearAppBadge) jobs.push(navigator.clearAppBadge().catch(function () {}));
    if ("serviceWorker" in navigator) {
      jobs.push(navigator.serviceWorker.getRegistration().then(function (reg) {
        if (!reg || !reg.pushManager) return;
        return reg.pushManager.getSubscription().then(function (sub) {
          if (!sub) return;
          return postJSON("/app/push/unsubscribe/", { endpoint: sub.endpoint })
            .catch(function () {})
            .then(function () { return sub.unsubscribe(); });
        });
      }).catch(function () {}));
    }
    var timeout = new Promise(function (resolve) { setTimeout(resolve, 2500); });
    return Promise.race([Promise.all(jobs).catch(function () {}), timeout]);
  }
  document.querySelectorAll('form[action$="/accounts/logout/"]').forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (form.dataset.cleared) return;
      e.preventDefault();
      form.dataset.cleared = "1";
      clearDeviceData().then(function () { form.submit(); });
    });
  });

  /* ---------- Notifications switch (More page) ---------- */
  var pushSwitch = document.querySelector("[data-push-toggle]");
  if (pushSwitch) {
    var note = document.querySelector("[data-push-note]");
    var testButton = document.querySelector("[data-push-test]");
    var setNote = function (text, tone) {
      if (!note) return;
      note.textContent = text;
      if (tone) note.dataset.tone = tone; else delete note.dataset.tone;
    };
    var keyToBytes = function (key) {
      var padded = (key + "===".slice((key.length + 3) % 4)).replace(/-/g, "+").replace(/_/g, "/");
      var raw = atob(padded), out = new Uint8Array(raw.length);
      for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
      return out;
    };
    var supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
    var iOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

    if (!pushSwitch.dataset.key) {
      pushSwitch.disabled = true;
      setNote("Notifications haven't been set up on this server yet.");
    } else if (!supported) {
      pushSwitch.disabled = true;
      setNote(iOS && !isApp
        ? "On iPhone, add the app to your Home Screen first, then turn notifications on from the app."
        : "This browser can't show notifications.");
    } else if (Notification.permission === "denied") {
      pushSwitch.disabled = true;
      setNote("Notifications are blocked. Turn them on for this app in your phone's Settings.", "error");
    } else {
      navigator.serviceWorker.ready.then(function (reg) {
        return reg.pushManager.getSubscription();
      }).then(function (sub) {
        pushSwitch.checked = !!sub;
        if (testButton) testButton.hidden = !sub;
      });
    }

    pushSwitch.addEventListener("change", function () {
      var turnOn = pushSwitch.checked;
      pushSwitch.disabled = true;
      navigator.serviceWorker.ready.then(function (reg) {
        if (!turnOn) {
          return reg.pushManager.getSubscription().then(function (sub) {
            if (!sub) return;
            return postJSON(pushSwitch.dataset.unsubscribeUrl, { endpoint: sub.endpoint }).then(function () { return sub.unsubscribe(); });
          }).then(function () { setNote("Notifications are off on this phone."); });
        }
        return Notification.requestPermission().then(function (permission) {
          if (permission !== "granted") throw new Error("denied");
          return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyToBytes(pushSwitch.dataset.key) });
        }).then(function (sub) {
          return postJSON(pushSwitch.dataset.subscribeUrl, sub.toJSON()).then(function (r) {
            if (!r.ok) { sub.unsubscribe(); throw new Error("server"); }
          });
        }).then(function () {
          setNote("Notifications are on. You'll hear about schedule changes and final scores.");
        });
      }).catch(function (err) {
        pushSwitch.checked = false;
        setNote(err && err.message === "denied"
          ? "You didn't allow notifications. You can change this in your phone's Settings."
          : "Couldn't turn notifications on. Please try again.", "error");
      }).then(function () {
        pushSwitch.disabled = false;
        if (testButton) testButton.hidden = !pushSwitch.checked;
      });
    });

    if (testButton) {
      testButton.addEventListener("click", function () {
        postJSON(testButton.dataset.url).then(function () { showToast("Test notification sent."); });
      });
    }
  }

  /* ---------- Theme choice (More page) ---------- */
  var themeButtons = document.querySelectorAll("[data-theme-value]");
  function markTheme() {
    var current = root.dataset.themeChoice || "auto";
    themeButtons.forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.themeValue === current)); });
  }
  themeButtons.forEach(function (b) {
    b.addEventListener("click", function () { if (window.setTheme) window.setTheme(b.dataset.themeValue); markTheme(); });
  });
  markTheme();

  /* ---------- "Get the app" banner in a phone browser tab ---------- */
  var banner = document.querySelector(".app-install");
  var snoozed = Number(store("getItem", "app-install-snooze") || 0) > Date.now();
  var phone = window.matchMedia && window.matchMedia("(max-width: 820px) and (pointer: coarse)").matches;
  if (banner && !isApp && phone && !snoozed) {
    var go = banner.querySelector("[data-install-go]");
    var how = banner.querySelector("[data-install-how]");
    var deferred = null;
    banner.querySelector("[data-install-dismiss]").addEventListener("click", function () {
      banner.hidden = true;
      store("setItem", "app-install-snooze", String(Date.now() + 14 * 24 * 3600 * 1000));
    });
    window.addEventListener("beforeinstallprompt", function (e) {
      e.preventDefault();
      deferred = e;
      how.textContent = "Faster, full screen, with notifications.";
      go.hidden = false;
      banner.hidden = false;
    });
    go.addEventListener("click", function () {
      if (!deferred) return;
      deferred.prompt();
      deferred.userChoice.finally(function () { deferred = null; banner.hidden = true; });
    });
    window.addEventListener("appinstalled", function () { banner.hidden = true; });
    if (/iPhone|iPad|iPod/.test(navigator.userAgent)) {
      how.textContent = "Tap Share, then “Add to Home Screen”.";
      setTimeout(function () { banner.hidden = false; }, 1500);
    }
  }
})();
