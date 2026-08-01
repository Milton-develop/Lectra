/* ===========================================================================
   Lectra — mobile interactions
   Splash, offline detection + queue, toasts, FAB bottom sheet, pull-to-refresh
   and background-sync handshake. Loaded after app.js.
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
  window.addEventListener('online', function () {
    setOffline(false);
    flushQueue();
  });
  window.addEventListener('offline', function () { setOffline(true); });
  if (!navigator.onLine) setOffline(true);

  /* ---- FAB bottom sheet ---- */
  var fabBtn = document.getElementById('fabBtn');
  var fabSheet = document.getElementById('fabSheet');
  function closeSheet() {
    if (fabSheet) fabSheet.classList.remove('open');
  }
  if (fabBtn && fabSheet) {
    fabBtn.addEventListener('click', function () { fabSheet.classList.add('open'); });
    fabSheet.addEventListener('click', function (e) {
      if (e.target.closest('[data-sheet-close]')) closeSheet();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeSheet();
    });
    fabSheet.querySelectorAll('a.sheet-option').forEach(function (link) {
      link.addEventListener('click', closeSheet);
    });
  }

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

  /* ---- Offline queue for schedule creation ---- */
  var QUEUE_KEY = 'lectra_schedule_queue';

  function readQueue() {
    try { return JSON.parse(localStorage.getItem(QUEUE_KEY)) || []; } catch (e) { return []; }
  }
  function writeQueue(queue) {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
  }

  function enqueueSchedule(obj) {
    var queue = readQueue();
    queue.push(obj);
    writeQueue(queue);
    toast('Saved offline — will sync when you reconnect', 'warn');
  }

  function flushQueue() {
    var queue = readQueue();
    if (!queue.length || !navigator.onLine) return;
    var remaining = [];
    var synced = 0;
    function next(i) {
      if (i >= queue.length) {
        writeQueue(remaining);
        if (synced) {
          toast(synced + (synced > 1 ? ' schedules' : ' schedule') + ' synced', 'success');
        }
        return;
      }
      fetch('/api/schedules', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': getToken()
        },
        body: JSON.stringify(queue[i])
      }).then(function (res) {
        if (res.ok) { synced++; } else { remaining.push(queue[i]); }
        next(i + 1);
      }).catch(function () {
        remaining.push(queue[i]);
        next(i + 1);
      });
    }
    next(0);
  }

  var createForm = document.querySelector('.form-card');
  if (createForm && /\/schedule\/new$/.test(createForm.getAttribute('action') || '')) {
    createForm.addEventListener('submit', function (e) {
      if (navigator.onLine) return;
      e.preventDefault();
      var fd = new FormData(createForm);
      var obj = {};
      fd.forEach(function (value, key) {
        if (key === 'reminder_minutes') {
          if (!obj[key]) obj[key] = [];
          obj[key].push(Number(value));
        } else if (key !== '_csrf_token') {
          obj[key] = value;
        }
      });
      enqueueSchedule(obj);
      window.location.href = '/calendar';
    });
  }
  flushQueue();

  /* ---- Background sync handshake (service worker -> page) ---- */
  if (navigator.serviceWorker) {
    navigator.serviceWorker.addEventListener('message', function (event) {
      if (event.data && event.data.type === 'flush-queue') flushQueue();
    });
    if (navigator.serviceWorker.ready && 'sync' in navigator.serviceWorker) {
      navigator.serviceWorker.ready.then(function (reg) {
        if (reg.sync) {
          reg.sync.register('sync-schedules')['catch'](function () {});
        }
      });
    }
  }
})();
