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
  var darkModeToggle = document.getElementById('darkModeToggle');

  function applyDarkMode(next) {
    document.body.classList.toggle('dark', next);
    if (darkModeToggle) darkModeToggle.checked = next;
    api('/api/settings', { method: 'PUT', body: { dark_mode: next } })['catch'](function () {});
  }

  if (themeToggle) {
    themeToggle.addEventListener('click', function () {
      applyDarkMode(!document.body.classList.contains('dark'));
    });
  }
  if (darkModeToggle) {
    darkModeToggle.addEventListener('change', function () {
      applyDarkMode(darkModeToggle.checked);
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

  /* ---- Defence interest toggle ---- */
  var defenceList = document.querySelector('.defence-list');
  if (defenceList) {
    defenceList.addEventListener('change', function (e) {
      var target = e.target;
      if (!target || !target.classList) return;

      if (target.classList.contains('interest-check')) {
        var id = target.getAttribute('data-id');
        var row = target.closest('.defence-item');
        var minutesSel = row ? row.querySelector('.interest-minutes') : null;

        if (target.checked) {
          var minutes = minutesSel ? parseInt(minutesSel.value, 10) : 30;
          api('/api/defences/' + id + '/interest', { method: 'PUT', body: { reminder_minutes: minutes } })
            .then(function (json) {
              if (json && json.ok) {
                if (minutesSel) minutesSel.disabled = false;
                if (row) row.classList.add('ticked');
                showToast('You will be reminded before this defence.', 'success');
              } else {
                target.checked = false;
                showToast((json && json.error) || 'Could not save your interest.', 'error');
              }
            })
            ['catch'](function () {
              target.checked = false;
              showToast('Could not save your interest.', 'error');
            });
        } else {
          api('/api/defences/' + id + '/interest', { method: 'DELETE' })
            .then(function (json) {
              if (json && json.ok) {
                if (minutesSel) minutesSel.disabled = true;
                if (row) row.classList.remove('ticked');
                showToast('Removed from your picks.', 'success');
              } else {
                target.checked = true;
                showToast((json && json.error) || 'Could not remove your interest.', 'error');
              }
            })
            ['catch'](function () {
              target.checked = true;
              showToast('Could not remove your interest.', 'error');
            });
        }
      } else if (target.classList.contains('interest-minutes')) {
        var id2 = target.getAttribute('data-id');
        var row2 = target.closest('.defence-item');
        var check = row2 ? row2.querySelector('.interest-check') : null;
        if (!check || !check.checked) return;
        var value = parseInt(target.value, 10);
        if (isNaN(value)) return;
        api('/api/defences/' + id2 + '/interest', { method: 'PUT', body: { reminder_minutes: value } })
          .then(function (json) {
            if (json && json.ok) {
              showToast('Reminder updated.', 'success');
            } else {
              showToast((json && json.error) || 'Could not update the reminder.', 'error');
            }
          })
          ['catch'](function () {
            showToast('Could not update the reminder.', 'error');
          });
      }
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

  var statusEl = document.getElementById('pushStatus');
  if (statusEl) {
    function appendErr(msg) {
      var text = String((msg && msg.message) ? msg.message : msg);
      if (statusEl.textContent.indexOf(text) === -1) {
        statusEl.textContent += ' | ERR: ' + text;
      }
    }
    window.addEventListener('unhandledrejection', function (e) {
      appendErr(e.reason);
    });
    window.addEventListener('error', function (e) {
      appendErr(e.error || e.message);
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
      var supported = OneSignal.Notifications.isPushSupported
        ? OneSignal.Notifications.isPushSupported()
        : 'unknown';
      parts.push('Supported: ' + supported);
      parts.push('Permission: ' + String(OneSignal.Notifications.permissionNative || 'unknown'));
      var ps = OneSignal.User.PushSubscription;
      if (ps) {
        parts.push('Opted in: ' + (ps.optedIn ? 'yes' : 'no'));
        parts.push('OS id: ' + (ps.id ? 'yes' : 'none'));
        parts.push('Token: ' + (ps.token ? 'present' : 'none'));
      }
      if ('serviceWorker' in navigator) {
        return navigator.serviceWorker.getRegistrations().then(function (regs) {
          var info = regs.length
            ? regs.map(function (r) {
                var u = r.active ? r.active.scriptURL : 'installing';
                return u.replace(location.origin, '');
              })
            : ['none'];
          parts.push('Workers: ' + info.join(', '));
          return Promise.all(regs.map(function (r) {
            return r.pushManager ? r.pushManager.getSubscription() : null;
          })).then(function (subs) {
            var browserSubs = subs.filter(Boolean);
            parts.push('Browser sub: ' + (browserSubs.length ? 'yes' : 'no'));
            el.textContent = parts.join(' \u00b7 ');
          });
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

  /* ---- Help & Support ---- */
  var faqSearch = document.getElementById('faqSearch');
  if (faqSearch) {
    var faqDetails = Array.prototype.slice.call(document.querySelectorAll('.help-faq details'));
    faqSearch.addEventListener('input', function () {
      var term = faqSearch.value.trim().toLowerCase();
      faqDetails.forEach(function (item) {
        var match = term === '' || item.textContent.toLowerCase().indexOf(term) !== -1;
        item.classList.toggle('is-hidden', !match);
        if (!match && item.open) item.open = false;
      });
      var groups = document.querySelectorAll('.help-faq');
      groups.forEach(function (group) {
        var visible = group.querySelectorAll('details:not(.is-hidden)').length > 0;
        var groupTitle = group.previousElementSibling;
        if (groupTitle && groupTitle.classList.contains('help-group-title')) {
          groupTitle.style.display = visible ? '' : 'none';
        }
        group.style.display = visible ? '' : 'none';
      });
    });
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
