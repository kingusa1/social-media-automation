/* AutoPost — Shared Utilities */

async function fetchAPI(url, options) {
    options = options || {};
    var resp = await fetch(url, options);
    if (!resp.ok) {
        var text = await resp.text();
        throw new Error(text || 'HTTP ' + resp.status);
    }
    return resp.json();
}

function statusColor(status) {
    var map = {
        success: 'success',
        failed: 'danger',
        partial_failure: 'warning',
        running: 'info',
        error: 'danger',
        warning: 'warning',
        never: 'secondary',
    };
    return map[status] || 'secondary';
}

function formatTime(isoStr) {
    if (!isoStr) return '-';
    try {
        var s = isoStr;
        if (!s.endsWith('Z') && s.indexOf('+') === -1 && s.lastIndexOf('-') < 10) s += 'Z';
        var d = new Date(s);
        var now = new Date();
        var diffMs = now - d;
        var diffMin = Math.floor(diffMs / 60000);
        var diffHr = Math.floor(diffMs / 3600000);
        var diffDay = Math.floor(diffMs / 86400000);

        if (diffMin < 1) return 'Just now';
        if (diffMin < 60) return diffMin + 'm ago';
        if (diffHr < 24) return diffHr + 'h ago';
        if (diffDay < 7) return diffDay + 'd ago';
        return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    } catch(e) {
        return isoStr;
    }
}

function formatFutureTime(isoStr) {
    if (!isoStr) return '-';
    try {
        var s = isoStr;
        if (!s.endsWith('Z') && s.indexOf('+') === -1 && s.lastIndexOf('-') < 10) s += 'Z';
        var d = new Date(s);
        var dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        var monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        var h = d.getUTCHours();
        var m = d.getUTCMinutes();
        var ampm = h >= 12 ? 'PM' : 'AM';
        var h12 = h === 0 ? 12 : (h > 12 ? h - 12 : h);
        return dayNames[d.getUTCDay()] + ', ' + monthNames[d.getUTCMonth()] + ' ' +
               d.getUTCDate() + ' at ' + h12 + ':' + (m < 10 ? '0' : '') + m + ' ' + ampm + ' UTC';
    } catch(e) {
        return isoStr;
    }
}

function showToast(message, type) {
    type = type || 'info';
    var icons = {
        success: 'check-circle-fill',
        danger: 'exclamation-triangle-fill',
        warning: 'exclamation-triangle-fill',
        info: 'info-circle-fill',
    };
    var icon = icons[type] || 'info-circle-fill';

    var container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    var id = 'toast-' + Date.now();
    var html = '<div id="' + id + '" class="toast align-items-center text-bg-' + type + ' border-0" role="alert">' +
        '<div class="d-flex">' +
            '<div class="toast-body"><i class="bi bi-' + icon + ' me-2"></i>' + message + '</div>' +
            '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>' +
        '</div>' +
    '</div>';
    container.insertAdjacentHTML('beforeend', html);

    var toastEl = document.getElementById(id);
    var toast = new bootstrap.Toast(toastEl, {delay: 4000});
    toast.show();
    toastEl.addEventListener('hidden.bs.toast', function() { toastEl.remove(); });
}

/* Format a UTC Date as "Mon, Feb 24 at 3:00 PM UTC" */
function _formatCronDate(candidate) {
    var dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    var monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    var h = candidate.getUTCHours();
    var m = candidate.getUTCMinutes();
    var ampm = h >= 12 ? 'PM' : 'AM';
    var h12 = h === 0 ? 12 : (h > 12 ? h - 12 : h);
    return dayNames[candidate.getUTCDay()] + ', ' + monthNames[candidate.getUTCMonth()] + ' ' +
           candidate.getUTCDate() + ' at ' + h12 + ':' + (m < 10 ? '0' : '') + m + ' ' + ampm + ' UTC';
}

/* Compute next run from a single cron string */
function _nextFromCron(cronStr) {
    var parts = cronStr.trim().split(/\s+/);
    if (parts.length < 5) return null;

    var minute = parseInt(parts[0]);
    var hour = parseInt(parts[1]);
    var dow = parts[4];

    var allowedDays = null;
    if (dow !== '*') {
        allowedDays = [];
        dow.split(',').forEach(function(chunk) {
            if (chunk.indexOf('-') > -1) {
                var range = chunk.split('-');
                for (var d = parseInt(range[0]); d <= parseInt(range[1]); d++) allowedDays.push(d);
            } else {
                allowedDays.push(parseInt(chunk));
            }
        });
    }

    var now = new Date();
    var candidate = new Date(Date.UTC(
        now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), hour, minute, 0
    ));
    if (candidate <= now) candidate.setUTCDate(candidate.getUTCDate() + 1);
    if (allowedDays) {
        for (var tries = 0; tries < 7; tries++) {
            if (allowedDays.indexOf(candidate.getUTCDay()) >= 0) break;
            candidate.setUTCDate(candidate.getUTCDate() + 1);
        }
    }
    return candidate;
}

/* Compute next cron run — handles both simple string and per-platform array */
function nextCronRun(cron) {
    if (!cron) return 'Not scheduled';

    // Handle JSON array format: [{"cron": "...", "platforms": [...]}, ...]
    var entries = [];
    if (Array.isArray(cron)) {
        entries = cron;
    } else if (typeof cron === 'string' && cron.trim().charAt(0) === '[') {
        try { entries = JSON.parse(cron); } catch(e) { entries = []; }
    }

    if (entries.length > 0) {
        var earliest = null;
        for (var i = 0; i < entries.length; i++) {
            var c = entries[i].cron || entries[i];
            var candidate = _nextFromCron(c);
            if (candidate && (!earliest || candidate < earliest)) earliest = candidate;
        }
        return earliest ? _formatCronDate(earliest) : 'Not scheduled';
    }

    // Simple cron string
    if (typeof cron !== 'string') return 'Not scheduled';
    var candidate = _nextFromCron(cron);
    return candidate ? _formatCronDate(candidate) : cron;
}

/* Cron helper: human-readable description */
function describeCron(cron) {
    if (!cron) return 'Not scheduled';
    var parts = cron.trim().split(/\s+/);
    if (parts.length < 5) return cron;

    var min = parts[0];
    var hour = parts[1];
    var dow = parts[4];
    var dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

    var timeStr = '';
    if (hour !== '*' && min !== '*') {
        var h = parseInt(hour);
        var m = parseInt(min);
        var ampm = h >= 12 ? 'PM' : 'AM';
        var h12 = h === 0 ? 12 : (h > 12 ? h - 12 : h);
        timeStr = h12 + ':' + (m < 10 ? '0' : '') + m + ' ' + ampm + ' UTC';
    }

    if (parts[2] === '*' && parts[3] === '*') {
        if (dow === '*') return 'Every day at ' + timeStr;
        if (dow === '1-5') return 'Weekdays (Mon-Fri) at ' + timeStr;
        var days = dow.split(',').map(function(d) { return dayNames[parseInt(d)] || d; });
        return days.join(', ') + ' at ' + timeStr;
    }
    return cron;
}

/* Build cron from picker values */
function buildCron(frequency, hour, minute, days) {
    var h = parseInt(hour) || 0;
    var m = parseInt(minute) || 0;
    if (frequency === 'daily') return m + ' ' + h + ' * * *';
    if (frequency === 'weekdays') return m + ' ' + h + ' * * 1-5';
    if (frequency === 'custom' && days && days.length > 0) return m + ' ' + h + ' * * ' + days.join(',');
    return m + ' ' + h + ' * * *';
}

/* Parse cron into picker values */
function parseCron(cron) {
    var result = { frequency: 'daily', hour: '10', minute: '0', days: [] };
    if (!cron) return result;
    var parts = cron.trim().split(/\s+/);
    if (parts.length < 5) return result;

    result.minute = parts[0];
    result.hour = parts[1];
    var dow = parts[4];

    if (dow === '*') {
        result.frequency = 'daily';
    } else if (dow === '1-5') {
        result.frequency = 'weekdays';
    } else {
        result.frequency = 'custom';
        result.days = dow.split(',');
    }
    return result;
}
