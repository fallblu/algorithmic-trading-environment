/* ============================================
   Toast Notification System
   ============================================ */

(function () {
  'use strict';

  var DISMISS_DELAY = 5000;
  var container = null;

  function getContainer() {
    if (container) return container;

    container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container';
      document.body.appendChild(container);
    }
    return container;
  }

  /**
   * Show a toast notification.
   * @param {string} message - The message to display.
   * @param {string} [type='info'] - One of: success, error, warning, info.
   */
  function showToast(message, type) {
    type = type || 'info';

    var toast = document.createElement('div');
    toast.className = 'toast toast-' + type;

    var icons = {
      success: '\u2713',
      error: '\u2717',
      warning: '\u26A0',
      info: '\u2139'
    };

    var icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.textContent = icons[type] || icons.info;

    var msg = document.createElement('span');
    msg.className = 'toast-message';
    msg.textContent = message;

    var closeBtn = document.createElement('button');
    closeBtn.className = 'toast-close';
    closeBtn.textContent = '\u00D7';
    closeBtn.addEventListener('click', function () {
      dismissToast(toast);
    });

    toast.appendChild(icon);
    toast.appendChild(msg);
    toast.appendChild(closeBtn);

    getContainer().appendChild(toast);

    // Auto-dismiss
    var timer = setTimeout(function () {
      dismissToast(toast);
    }, DISMISS_DELAY);

    // Pause auto-dismiss on hover
    toast.addEventListener('mouseenter', function () {
      clearTimeout(timer);
    });

    toast.addEventListener('mouseleave', function () {
      timer = setTimeout(function () {
        dismissToast(toast);
      }, DISMISS_DELAY);
    });
  }

  function dismissToast(toast) {
    if (toast.classList.contains('dismissing')) return;

    toast.classList.add('dismissing');

    toast.addEventListener('animationend', function () {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    });
  }

  // Expose globally
  window.showToast = showToast;
})();
