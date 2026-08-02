/* ===========================================================================
   Lectra — application scripts
   =========================================================================== */
(function () {
  'use strict';

  function getToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function api(url, options) {
    options = options || {};
    options.headers = options.headers || {};
    options.headers['X-CSRF-Token'] = getToken();
    if (options.body && typeof options.body !== 'string' && !(options.body instanceof FormData)) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(options.body);
    }
    return fetch(url, options).then(function (res) { return res.json(); });
  }

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  function getAppTz() {
    var body = document.body;
    return body && body.getAttribute('data-timezone') ? body.getAttribute('data-timezone') : undefined;
  }

  function formatTime(value, opts) {
    var d = new Date(value);
    if (isNaN(d.getTime())) return String(value == null ? '' : value);
    var tz = getAppTz();
    return d.toLocaleString(undefined, Object.assign({}, opts, tz ? { timeZone: tz } : {}));
  }

  /* ---- Flash messages auto-dismiss ---- */
  document.querySelectorAll('[data-flashes]').forEach(function (box) {
    setTimeout(function () {
      box.querySelectorAll('.alert').forEach(function (alertEl) {
        alertEl.style.transition = 'opacity .3s ease';
        alertEl.style.opacity = '0';
        setTimeout(function () { alertEl.remove(); }, 350);
      });
    }, 5000);
  });
  document.querySelectorAll('.alert-close').forEach(function (btn) {
    btn.addEventListener('click', function () { btn.parentElement.remove(); });
  });

  /* ---- Mobile navigation ---- */
  var menuBtn = document.getElementById('menuBtn');
  var backdrop = document.getElementById('backdrop');
  if (menuBtn && backdrop) {
    menuBtn.addEventListener('click', function () {
      document.body.classList.toggle('nav-open');
    });
    backdrop.addEventListener('click', function () {
      document.body.classList.remove('nav-open');
    });
  }

  /* ---- Theme toggle ---- */
  var themeToggle = document.getElementById('themeToggle');
  if (themeToggle) {
    themeToggle.addEventListener('click', function () {
      var body = document.body;
      var next = !body.classList.contains('dark');
      body.classList.toggle('dark', next);
      api('/api/settings', { method: 'PUT', body: { dark_mode: next } })['catch'](function () {});
    });
  }

  /* ---- Notifications ---- */
  var notifBtn = document.getElementById('notifBtn');
  var notifDropdown = document.getElementById('notifDropdown');

  document.querySelectorAll('[data-view-notifications]').forEach(function (el) {
    el.addEventListener('click', function (e) {
      e.preventDefault();
      if (notifBtn) notifBtn.click();
    });
  });

  if (notifBtn && notifDropdown) {
    notifBtn.addEventListener('click', function () {
      var open = notifDropdown.classList.contains('open');
      notifDropdown.classList.toggle('open', !open);
      if (!open) loadNotifications();
    });
    document.addEventListener('click', function (e) {
      if (!notifBtn.contains(e.target) && !notifDropdown.contains(e.target)) {
        notifDropdown.classList.remove('open');
      }
    });
  }

  function loadNotifications() {
    if (!notifDropdown) return;
    notifDropdown.innerHTML = '<div class="dropdown-head"><span>Notifications</span></div>';
    fetch('/api/notifications')
      .then(function (res) { return res.json(); })
      .then(function (json) {
        var list = json.data || [];
        if (!list.length) {
          notifDropdown.innerHTML += '<div class="empty-state"><p class="muted">You&rsquo;re all caught up.</p></div>';
        } else {
          var items = list.map(function (n) {
            return '<li class="notif-item' + (n.is_read ? '' : ' unread') + '" data-id="' + esc(n.id) + '">' +
              '<div class="notif-dot"></div><div>' +
              '<div class="notif-title">' + esc(n.title) + '</div>' +
              (n.message ? '<div class="notif-message">' + esc(n.message) + '</div>' : '') +
              '<div class="notif-time">' + esc(formatTime(n.created_at, {
                year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
              })) + '</div>' +
              '</div></li>';
          }).join('');
          notifDropdown.innerHTML += '<ul class="notif-list">' + items + '</ul>';
          notifDropdown.querySelectorAll('.notif-item').forEach(function (item) {
            item.addEventListener('click', function () {
              api('/api/notifications/' + item.getAttribute('data-id') + '/read', { method: 'POST' })
                .then(function () {
                  item.classList.remove('unread');
                  updateBadge();
                });
            });
          });
        }
        notifDropdown.innerHTML += '<div class="dropdown-foot"><button type="button" class="btn btn-ghost btn-sm" id="readAllBtn">Mark all as read</button></div>';
        var readAll = document.getElementById('readAllBtn');
        if (readAll) {
          readAll.addEventListener('click', function () {
            api('/api/notifications/read-all', { method: 'POST' }).then(function () {
              notifDropdown.querySelectorAll('.notif-item').forEach(function (i) {
                i.classList.remove('unread');
              });
              updateBadge();
            });
          });
        }
      })
      ['catch'](function () {
        notifDropdown.innerHTML += '<div class="empty-state"><p class="muted">Could not load notifications.</p></div>';
      });
  }

  function updateBadge() {
    if (!notifBtn) return;
    fetch('/api/notifications/unread-count')
      .then(function (res) { return res.json(); })
      .then(function (json) {
        var badge = document.getElementById('notifBadge');
        if (json.count > 0) {
          if (badge) {
            badge.textContent = json.count;
          } else {
            var b = document.createElement('span');
            b.className = 'badge';
            b.id = 'notifBadge';
            b.textContent = json.count;
            notifBtn.appendChild(b);
          }
        } else if (badge) {
          badge.remove();
        }
      })
      ['catch'](function () {});
  }

  /* ---- Notifications page: delete / mark all as read ---- */
  var notifPageList = document.getElementById('notifPageList');
  if (notifPageList) {
    notifPageList.addEventListener('click', function (e) {
      var btn = e.target.closest('.notif-delete');
      if (!btn) return;
      var item = btn.closest('.notif-item');
      var id = item.getAttribute('data-id');
      api('/api/notifications/' + id, { method: 'DELETE' }).then(function (json) {
        if (json.ok) {
          item.remove();
          if (!notifPageList.querySelector('.notif-item')) {
            var card = notifPageList.closest('.card');
            notifPageList.remove();
            var emptyDiv = document.createElement('div');
            emptyDiv.className = 'empty-state';
            emptyDiv.innerHTML = '<p>No notifications yet.</p>';
            card.appendChild(emptyDiv);
          }
          updateBadge();
        }
      })['catch'](function () {
        window.alert('Could not delete the notification.');
      });
    });
  }

  var readAllPageBtn = document.getElementById('readAllPageBtn');
  if (readAllPageBtn) {
    readAllPageBtn.addEventListener('click', function () {
      api('/api/notifications/read-all', { method: 'POST' }).then(function () {
        notifPageList.querySelectorAll('.notif-item').forEach(function (i) {
          i.classList.remove('unread');
        });
        readAllPageBtn.remove();
        updateBadge();
      });
    });
  }

  /* ---- Browser push notifications (OneSignal) ---- */
  function showToast(message, type) {
    var toast = document.createElement('div');
    toast.className = 'push-toast alert alert-' + (type || 'success');
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(function () {
      toast.style.transition = 'opacity .3s ease';
      toast.style.opacity = '0';
      setTimeout(function () { toast.remove(); }, 350);
    }, 4000);
  }

  function savePushPreference(enabled) {
    return api('/api/settings', { method: 'PUT', body: { push_notifications: enabled } });
  }

  function runWithOneSignal(task) {
    if (!window.OneSignalDeferred) {
      return Promise.reject(new Error('OneSignal is not configured on the server.'));
    }
    return new Promise(function (resolve, reject) {
      window.OneSignalDeferred.push(async function (OneSignal) {
        try {
          resolve(await task(OneSignal));
        } catch (error) {
          reject(error instanceof Error ? error : new Error(String(error)));
        }
      });
    });
  }

  function enablePushNotifications() {
    return runWithOneSignal(function (OneSignal) {
      return OneSignal.Notifications.requestPermission()
        .then(function () {
          if (OneSignal.Notifications.permissionNative === 'denied') {
            throw new Error('Permission to show notifications was not granted.');
          }
          return OneSignal.User.PushSubscription.optIn();
        })
        .then(function () {
          return savePushPreference(true);
        });
    });
  }

  function disablePushNotifications() {
    return runWithOneSignal(function (OneSignal) {
      return OneSignal.User.PushSubscription.optOut()
        .then(function () {
          return savePushPreference(false);
        });
    });
  }

  var pushToggle = document.getElementById('pushNotifications');
  if (pushToggle) {
    var pushBusy = false;
    pushToggle.addEventListener('change', function () {
      if (pushBusy) return;
      var turnOn = pushToggle.checked;
      pushBusy = true;
      pushToggle.disabled = true;
      var promise = turnOn ? enablePushNotifications() : disablePushNotifications();
      promise.then(function () {
        showToast(turnOn ? 'Push notifications enabled.' : 'Push notifications disabled.');
      })['catch'](function (error) {
        pushToggle.checked = !turnOn;
        showToast(error.message, 'error');
      }).then(function () {
        pushToggle.disabled = false;
        pushBusy = false;
        updatePushStatus();
      });
    });
  }

  function finishPushEnable(OneSignal) {
    return OneSignal.User.PushSubscription.optIn()
      .then(function () {
        return savePushPreference(true);
      });
  }

  function updatePushStatus() {
    var el = document.getElementById('pushStatus');
    if (!el) return;
    if (!window.OneSignalDeferred) {
      el.textContent = 'Push is not configured on the server.';
      return;
    }
    runWithOneSignal(function (OneSignal) {
      var parts = [];
      parts.push('Permission: ' + String(OneSignal.Notifications.permissionNative || 'unknown'));
      var ps = OneSignal.User.PushSubscription;
      if (ps) {
        parts.push('Subscribed: ' + (ps.optedIn ? 'yes' : 'no'));
        parts.push('Token: ' + (ps.token ? 'present' : 'none'));
      }
      if ('serviceWorker' in navigator) {
        return navigator.serviceWorker.getRegistrations().then(function (regs) {
          if (!regs.length) {
            parts.push('Workers: none');
          } else {
            var info = regs.map(function (r) {
              var url = r.active ? r.active.scriptURL : 'installing';
              return url.replace(location.origin, '');
            });
            parts.push('Workers: ' + info.join(', '));
          }
          el.textContent = parts.join(' \u00b7 ');
        });
      }
      el.textContent = parts.join(' \u00b7 ');
    })['catch'](function () {
      el.textContent = 'Push state unavailable.';
    });
  }

  updatePushStatus();

  var pushAutoEnabled = false;
  function autoSubscribePush() {
    if (document.body.getAttribute('data-push-enabled') !== '1') return;
    runWithOneSignal(function (OneSignal) {
      var native = OneSignal.Notifications.permissionNative;
      if (native === 'granted') {
        if (pushAutoEnabled) return null;
        pushAutoEnabled = true;
        return finishPushEnable(OneSignal);
      }
      if (native === 'default') {
        return OneSignal.Slidedown.promptPush().then(function () {
          if (OneSignal.Notifications.permissionNative === 'granted' && !pushAutoEnabled) {
            pushAutoEnabled = true;
            return finishPushEnable(OneSignal);
          }
        });
      }
    })['catch'](function () {});
  }

  autoSubscribePush();

  /* ---- Calendar ---- */
  var calGrid = document.getElementById('calGrid');
  if (calGrid) initCalendar();

  function initCalendar() {
    var calTitle = document.getElementById('calTitle');
    var dayDetailTitle = document.getElementById('dayDetailTitle');
    var dayDetailBody = document.getElementById('dayDetailBody');
    var prevBtn = document.getElementById('calPrev');
    var nextBtn = document.getElementById('calNext');
    var todayBtn = document.getElementById('calToday');

    var now = new Date();
    var viewYear = now.getFullYear();
    var viewMonth = now.getMonth();
    var events = [];
    var selectedDate = null;

    var monthNames = ['January', 'February', 'March', 'April', 'May', 'June',
      'July', 'August', 'September', 'October', 'November', 'December'];

    function pad(n) { return (n < 10 ? '0' : '') + n; }
    function iso(d) {
      return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    }

    function loadEvents() {
      var first = new Date(viewYear, viewMonth, 1);
      var last = new Date(viewYear, viewMonth + 1, 0);
      var skeleton = '';
      for (var s = 0; s < 35; s++) { skeleton += '<div class="cal-day skeleton"></div>'; }
      calGrid.innerHTML = skeleton;
      fetch('/api/schedules?start=' + iso(first) + '&end=' + iso(last))
        .then(function (res) { return res.json(); })
        .then(function (json) {
          events = json.data || [];
          render();
        })
        ['catch'](function () {
          calGrid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><p class="muted">Could not load schedules.</p></div>';
        });
    }

    function render() {
      calTitle.textContent = monthNames[viewMonth] + ' ' + viewYear;
      var first = new Date(viewYear, viewMonth, 1);
      var startDow = first.getDay();
      var daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
      var daysInPrev = new Date(viewYear, viewMonth, 0).getDate();
      var todayIso = iso(now);
      var byDate = {};
      events.forEach(function (e) {
        if (!byDate[e.event_date]) byDate[e.event_date] = [];
        byDate[e.event_date].push(e);
      });

      var html = '';
      var i, d;
      for (i = startDow - 1; i >= 0; i--) {
        d = new Date(viewYear, viewMonth - 1, daysInPrev - i);
        html += cell(d, true, byDate[iso(d)] || [], todayIso);
      }
      for (d = 1; d <= daysInMonth; d++) {
        var date = new Date(viewYear, viewMonth, d);
        html += cell(date, false, byDate[iso(date)] || [], todayIso);
      }
      var total = startDow + daysInMonth;
      var trailing = (7 - (total % 7)) % 7;
      for (d = 1; d <= trailing; d++) {
        var nxt = new Date(viewYear, viewMonth + 1, d);
        html += cell(nxt, true, byDate[iso(nxt)] || [], todayIso);
      }
      calGrid.innerHTML = html;

      calGrid.querySelectorAll('.cal-day').forEach(function (el) {
        el.addEventListener('click', function () {
          selectedDate = el.getAttribute('data-date');
          calGrid.querySelectorAll('.cal-day').forEach(function (c) {
            c.classList.remove('selected');
          });
          el.classList.add('selected');
          renderDayDetail(selectedDate);
        });
      });
    }

    function cell(date, otherMonth, dayEvents, todayIso) {
      var dIso = iso(date);
      var classes = ['cal-day'];
      if (otherMonth) classes.push('other');
      if (dIso === todayIso) classes.push('today');
      if (selectedDate === dIso) classes.push('selected');

      var eventsHtml = '';
      dayEvents.slice(0, 3).forEach(function (e) {
        eventsHtml += '<span class="cal-event" style="background:' + esc(e.color || '#4F46E5') + '">' +
          esc(e.start_time ? e.start_time.slice(0, 5) : '') + ' ' + esc(e.title) + '</span>';
      });
      if (dayEvents.length > 3) {
        eventsHtml += '<span class="cal-more">+' + (dayEvents.length - 3) + ' more</span>';
      }
      return '<div class="' + classes.join(' ') + '" data-date="' + dIso + '">' +
        '<span class="cal-day-num">' + date.getDate() + '</span>' +
        '<div class="cal-events">' + eventsHtml + '</div></div>';
    }

    function renderDayDetail(dateIso) {
      dayDetailTitle.textContent = formatDay(dateIso);
      var dayEvents = events.filter(function (e) { return e.event_date === dateIso; }).sort(function (a, b) {
        return (a.start_time || '').localeCompare(b.start_time || '');
      });
      if (!dayEvents.length) {
        dayDetailBody.innerHTML = '<p class="muted">No schedules on this day.</p>' +
          '<a class="btn btn-primary btn-sm" href="/schedule/new?date=' + dateIso + '">Add schedule</a>';
        return;
      }
      var items = dayEvents.map(function (e) {
        return '<li class="day-detail-item">' +
          '<div class="day-detail-time">' + esc(e.start_time ? e.start_time.slice(0, 5) : '') +
          (e.end_time ? ' &ndash; ' + esc(e.end_time.slice(0, 5)) : '') + '</div>' +
          '<div class="day-detail-title">' + esc(e.title) + '</div>' +
          (e.location ? '<div class="day-detail-meta">' + esc(e.location) + '</div>' : '') +
          '<div class="day-detail-actions">' +
          '<a class="btn btn-ghost btn-sm" href="/schedule/' + esc(e.id) + '/edit">Edit</a>' +
          '<button type="button" class="btn btn-danger btn-sm" data-delete="' + esc(e.id) + '">Delete</button>' +
          '</div></li>';
      }).join('');
      dayDetailBody.innerHTML = '<ul class="day-detail-list">' + items + '</ul>';
      dayDetailBody.querySelectorAll('[data-delete]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          if (!window.confirm('Delete this schedule?')) return;
          var scheduleId = btn.getAttribute('data-delete');
          api('/api/schedules/' + scheduleId, { method: 'DELETE' })
            .then(function (json) {
              if (json && json.ok) {
                loadEvents();
              } else {
                showToast((json && json.error) || 'Could not delete the schedule.', 'error');
              }
            });
        });
      });
    }

    function formatDay(dateIso) {
      var d = new Date(dateIso + 'T00:00:00');
      return d.toLocaleDateString(undefined, {
        weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
      });
    }

    prevBtn.addEventListener('click', function () {
      viewMonth--;
      if (viewMonth < 0) { viewMonth = 11; viewYear--; }
      selectedDate = null;
      loadEvents();
    });
    nextBtn.addEventListener('click', function () {
      viewMonth++;
      if (viewMonth > 11) { viewMonth = 0; viewYear++; }
      selectedDate = null;
      loadEvents();
    });
    todayBtn.addEventListener('click', function () {
      viewYear = now.getFullYear();
      viewMonth = now.getMonth();
      selectedDate = null;
      loadEvents();
    });

    var touchX = null;
    calGrid.addEventListener('touchstart', function (e) {
      touchX = e.touches[0].clientX;
    }, { passive: true });
    calGrid.addEventListener('touchend', function (e) {
      if (touchX === null) return;
      var dx = e.changedTouches[0].clientX - touchX;
      if (Math.abs(dx) > 60) {
        if (dx < 0) nextBtn.click(); else prevBtn.click();
      }
      touchX = null;
    }, { passive: true });

    loadEvents();
  }

  /* ---- Greeting card ---- */
  var greetText = document.getElementById('greetText');
  var greetDate = document.getElementById('greetDate');
  var greetTime = document.getElementById('greetTime');
  var appTz = (document.body && document.body.getAttribute('data-timezone')) || undefined;
  var tzOptions = appTz ? { timeZone: appTz } : {};
  if (greetText) {
    var name = greetText.textContent.split(', ')[1] || '';
    var icons = ['☀', '☀', '☁', '☾'];
    function greetingPeriod(h) {
      if (h >= 5 && h < 12) return { word: 'Good morning', icon: icons[0] };
      if (h >= 12 && h < 17) return { word: 'Good afternoon', icon: icons[1] };
      if (h >= 17 && h < 21) return { word: 'Good evening', icon: icons[2] };
      return { word: 'Good night', icon: icons[3] };
    }
    function localParts(date) {
      var opts = { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
      var parts = Object.assign({}, opts, tzOptions);
      return new Intl.DateTimeFormat(undefined, parts).formatToParts(date);
    }
    function greetingDate() {
      var opts = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
      return new Date().toLocaleDateString(undefined, Object.assign({}, opts, tzOptions));
    }
    function greetingTime() {
      var parts = localParts(new Date());
      var vals = {};
      parts.forEach(function (p) { vals[p.type] = p.value; });
      var hour = parseInt(vals.hour, 10);
      return new Date().toLocaleTimeString(undefined, Object.assign(
        { hour: '2-digit', minute: '2-digit', second: '2-digit' }, tzOptions
      ));
    }
    function updateGreeting() {
      var d = new Date();
      var hour = parseInt(localParts(d).filter(function (p) { return p.type === 'hour'; })[0].value, 10);
      var p = greetingPeriod(hour);
      greetText.textContent = p.word + ', ' + name;
      var icon = document.querySelector('.greeting-icon');
      if (icon) icon.textContent = p.icon;
      if (greetDate) {
        greetDate.textContent = greetingDate();
      }
      if (greetTime) {
        greetTime.textContent = greetingTime();
      }
    }
    updateGreeting();
    setInterval(updateGreeting, 1000);
  }
})();
