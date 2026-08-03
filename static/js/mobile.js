/* ===========================================================================
   Lectra — mobile interactions
   Splash, offline banner, toasts, pull-to-refresh. Loaded after app.js.
   =========================================================================== */
(function () {
  'use strict';

  function getToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  /* ---- Toasts ---- */
  function toast(message, type) {
    var wrap = document.getElementById('toastWrap');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.id = 'toastWrap';
      document.body.appendChild(wrap);
    }
    var el = document.createElement('div');
    el.className = 'toast' + (type ? ' ' + type : '');
    el.textContent = message;
    wrap.appendChild(el);
    requestAnimationFrame(function () { el.classList.add('show'); });
    setTimeout(function () {
      el.classList.remove('show');
      setTimeout(function () { el.remove(); }, 300);
    }, 2600);
  }
  window.toast = toast;

  /* ---- Splash screen ---- */
  var splash = document.getElementById('splash');
  if (splash) {
    setTimeout(function () {
      splash.classList.add('hide');
      setTimeout(function () {
        if (splash.parentNode) splash.parentNode.removeChild(splash);
      }, 450);
    }, 600);
  }

  /* ---- Offline banner ---- */
  var offlineBanner = document.getElementById('offlineBanner');
  function setOffline(offline) {
    if (offlineBanner) offlineBanner.hidden = !offline;
    if (offline) toast('You are offline', 'warn');
  }
  window.addEventListener('online', function () { setOffline(false); });
  window.addEventListener('offline', function () { setOffline(true); });
  if (!navigator.onLine) setOffline(true);

  /* ---- Pull to refresh ---- */
  var ptr = document.createElement('div');
  ptr.className = 'ptr-indicator';
  ptr.innerHTML = '<div class="ptr-spinner"></div>';
  document.body.appendChild(ptr);

  var pullStart = null;
  var pullDelta = 0;
  var refreshing = false;
  document.addEventListener('touchstart', function (e) {
    if (window.scrollY <= 0 && !refreshing) {
      pullStart = e.touches[0].clientY;
      pullDelta = 0;
    }
  }, { passive: true });
  document.addEventListener('touchmove', function (e) {
    if (pullStart === null || refreshing) return;
    var dy = e.touches[0].clientY - pullStart;
    if (dy > 0 && window.scrollY <= 0) {
      pullDelta = Math.min(dy * 0.5, 60);
      ptr.style.height = pullDelta + 'px';
    }
  }, { passive: true });
  document.addEventListener('touchend', function () {
    if (pullStart === null) return;
    pullStart = null;
    if (pullDelta >= 48 && !refreshing) {
      refreshing = true;
      ptr.style.height = '48px';
      window.location.reload();
    } else {
      ptr.style.height = '0px';
    }
    pullDelta = 0;
  }, { passive: true });
})();
