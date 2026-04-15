/* ═══════════════════════════════════════════════════════════════════════════
   GPU Monitor — Modern Dashboard
   ═══════════════════════════════════════════════════════════════════════════ */

var py_exec = "/home/bizon/anaconda3/bin/python3";
var _core_path = "/usr/local/share/dlbt_os/";
var _working_mode = "dev";
var _tab_name = "gpu";
var py_path = _core_path + "cockpit_" + _tab_name + "/py_backend/";

var _gpu_fields = ["temperature", "gpu_utilization", "memory_utilization", "power_usage"];
var _active_field = "temperature";
var _initial_load_done = false;
var _plotting_data = {};
var _sampling_size = 550;
var _samples = [];
var _chart = undefined;
var _gpu_colors = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff", "#db6d28", "#f778ba", "#79c0ff"];

// Real-time chart data (collected from live GPU polls every 5s)
var _rt_samples = [];
var _rt_max = 120; // keep last 10 minutes at 5s intervals
var _rt_counter = 0;
var _last_gpus = null;

/* ─── Helpers ────────────────────────────────────────────────────────────── */

function tempColor(t) {
    if (t < 50) return "green";
    if (t < 75) return "yellow";
    return "red";
}
function utilColor(u) {
    if (u < 50) return "green";
    if (u < 80) return "yellow";
    return "red";
}
function showToast(msg, isError) {
    var el = document.getElementById("toast");
    el.textContent = msg;
    el.className = "toast show" + (isError ? " error" : "");
    setTimeout(function() { el.className = "toast"; }, 3000);
}

/* ─── GPU Data Fetch ─────────────────────────────────────────────────────── */

function load_gpus() {
    cockpit.spawn([py_exec, py_path + "gpu_backend.py"], {})
        .stream(function(data) {
            try {
                var gpus = JSON.parse(data);
                _last_gpus = gpus;
                render_gpus(gpus);
            } catch(e) {}
        })
        .catch(function(err) { console.log("GPU fetch error:", err); });
}

function collect_rt_sample() {
    if (!_last_gpus || !_last_gpus.length) return;
    var now = new Date();
    var ts = String(now.getHours()).padStart(2,'0') + ':' + String(now.getMinutes()).padStart(2,'0') + ':' + String(now.getSeconds()).padStart(2,'0');
    _rt_samples.push({ timestamp: ts, data: _last_gpus });
    if (_rt_samples.length > _rt_max) _rt_samples.shift();
    // Build chart data from real-time samples
    _gpu_fields.forEach(function(f) { _plotting_data[f] = build_chart_data(_rt_samples.map(function(s) { return { timestamp: '2000-01-01 ' + s.timestamp, data: s.data }; }), f); });
    render_chart();
    var info = document.getElementById('chart-info');
    if (info) info.textContent = _rt_samples.length + ' samples collected (updates every 5s) — Logger writes to disk every 5 min for long-term history.';
}

/* ─── Render GPU Cards ───────────────────────────────────────────────────── */

function render_gpus(gpus) {
    var grid = document.getElementById("gpu-grid");
    document.getElementById("gpu-count").textContent = gpus.length + " GPU" + (gpus.length !== 1 ? "s" : "");

    // Update in place if card count matches
    if (grid.children.length === gpus.length) {
        gpus.forEach(function(gpu, idx) { update_card(gpu, idx); });
        return;
    }

    // First render — build cards
    var html = "";
    gpus.forEach(function(gpu, idx) {
        var tc = tempColor(gpu.temperature);
        var uc = utilColor(gpu.gpu_utilization);
        var mc = utilColor(gpu.memory_pct);
        html += '<div class="gpu-card" id="gpu-card-' + idx + '">'
            + '<div class="gpu-card-header">'
            + '  <span class="gpu-name">' + gpu.name + '</span>'
            + '  <span class="gpu-id">GPU ' + gpu.id + '</span>'
            + '</div>'
            + '<div class="metrics-grid">'
            + '  <div class="metric">'
            + '    <div class="metric-label">Temperature</div>'
            + '    <div class="metric-value color-' + tc + '" id="temp-' + idx + '">' + gpu.temperature + '°C</div>'
            + '    <div class="metric-bar"><div class="metric-bar-fill bar-' + tc + '" id="temp-bar-' + idx + '" style="width:' + Math.min(gpu.temperature, 100) + '%"></div></div>'
            + '  </div>'
            + '  <div class="metric">'
            + '    <div class="metric-label">GPU Utilization</div>'
            + '    <div class="metric-value color-' + uc + '" id="util-' + idx + '">' + gpu.gpu_utilization + '%</div>'
            + '    <div class="metric-bar"><div class="metric-bar-fill bar-' + uc + '" id="util-bar-' + idx + '" style="width:' + gpu.gpu_utilization + '%"></div></div>'
            + '  </div>'
            + '  <div class="metric">'
            + '    <div class="metric-label">Memory</div>'
            + '    <div class="metric-value color-accent" id="mem-' + idx + '">' + gpu.memory_used + ' <span class="unit">/ ' + gpu.memory_total + ' MB</span></div>'
            + '    <div class="metric-bar"><div class="metric-bar-fill bar-accent" id="mem-bar-' + idx + '" style="width:' + gpu.memory_pct + '%"></div></div>'
            + '    <div class="metric-sub" id="mem-pct-' + idx + '">' + gpu.memory_pct + '% used</div>'
            + '  </div>'
            + '  <div class="metric">'
            + '    <div class="metric-label">Fan / Power</div>'
            + '    <div class="metric-value" id="fan-power-' + idx + '">'
            + '      <span class="color-purple">' + gpu.fan + '%</span>'
            + '      <span style="color:var(--text-muted);font-size:14px;margin:0 4px">/</span>'
            + '      <span class="color-orange" style="color:var(--orange)">' + gpu.power_usage + 'W</span>'
            + '    </div>'
            + '  </div>'
            + '</div>'
            + '<div class="power-section">'
            + '  <div class="power-header">'
            + '    <span class="power-label">⚡ Power Limit</span>'
            + '    <span class="power-value" id="power-display-' + idx + '">' + gpu.power_usage + 'W current</span>'
            + '  </div>'
            + '  <div class="power-row">'
            + '    <input type="range" class="power-slider" id="power-slider-' + idx + '" min="100" max="600" value="' + gpu.power_usage + '" data-gpu="' + idx + '">'
            + '    <input type="number" class="power-input" id="power-input-' + idx + '" value="' + gpu.power_usage + '" min="100" max="600">'
            + '    <span class="unit">W</span>'
            + '    <button class="btn-apply" id="power-apply-' + idx + '" data-gpu="' + idx + '">Apply</button>'
            + '  </div>'
            + '</div>'
            + '</div>';
    });
    grid.innerHTML = html;

    // Attach power control events
    gpus.forEach(function(gpu, idx) {
        var slider = document.getElementById("power-slider-" + idx);
        var input = document.getElementById("power-input-" + idx);
        var btn = document.getElementById("power-apply-" + idx);

        slider.addEventListener("input", function() { input.value = slider.value; });
        input.addEventListener("input", function() { slider.value = input.value; });
        btn.addEventListener("click", function() { apply_power(idx, input.value); });
    });
}

function update_card(gpu, idx) {
    var tc = tempColor(gpu.temperature);
    var uc = utilColor(gpu.gpu_utilization);
    var mc = utilColor(gpu.memory_pct);

    var el;
    el = document.getElementById("temp-" + idx);
    if (el) { el.textContent = gpu.temperature + "°C"; el.className = "metric-value color-" + tc; }
    el = document.getElementById("temp-bar-" + idx);
    if (el) { el.style.width = Math.min(gpu.temperature, 100) + "%"; el.className = "metric-bar-fill bar-" + tc; }

    el = document.getElementById("util-" + idx);
    if (el) { el.textContent = gpu.gpu_utilization + "%"; el.className = "metric-value color-" + uc; }
    el = document.getElementById("util-bar-" + idx);
    if (el) { el.style.width = gpu.gpu_utilization + "%"; el.className = "metric-bar-fill bar-" + uc; }

    el = document.getElementById("mem-" + idx);
    if (el) { el.innerHTML = gpu.memory_used + ' <span class="unit">/ ' + gpu.memory_total + ' MB</span>'; }
    el = document.getElementById("mem-bar-" + idx);
    if (el) { el.style.width = gpu.memory_pct + "%"; }
    el = document.getElementById("mem-pct-" + idx);
    if (el) { el.textContent = gpu.memory_pct + "% used"; }

    el = document.getElementById("fan-power-" + idx);
    if (el) {
        el.innerHTML = '<span class="color-purple">' + gpu.fan + '%</span>'
            + '<span style="color:var(--text-muted);font-size:14px;margin:0 4px">/</span>'
            + '<span style="color:var(--orange)">' + gpu.power_usage + 'W</span>';
    }
    el = document.getElementById("power-display-" + idx);
    if (el) { el.textContent = gpu.power_usage + "W current"; }
}

/* ─── Power Control ──────────────────────────────────────────────────────── */

function apply_power(gpu_id, power) {
    var args = [py_exec, py_path + "hw_interface.py", "--gpu_id=" + gpu_id, "--power=" + power];
    cockpit.spawn(args, { superuser: "require" })
        .stream(function(data) {
            try {
                var r = JSON.parse(data);
                if (r.success) showToast("✓ Power limit set to " + power + "W on GPU " + gpu_id, false);
                else showToast("✗ " + (r.output || "Failed to apply"), true);
            } catch(e) {}
        })
        .catch(function(err) { showToast("✗ Error: " + err.message, true); });
}

/* ─── History Chart ──────────────────────────────────────────────────────── */

function get_logs(initialize) {
    var last_sample = "NIL";
    var stream_call = initialize ? initial_fill_stream : update_stream;
    if (_samples.length > 0) last_sample = _samples[_samples.length - 1]["timestamp"];

    var args = [py_exec, py_path + "read_history.py",
                "--last_log=\"" + last_sample + "\"",
                "--sampling_size=" + _sampling_size];
    cockpit.spawn(args)
        .stream(stream_call)
        .catch(function(err) { console.log("History fetch error:", err); });
}

function update_stream(data) {
    try {
        var resp = JSON.parse(data);
        var nsamples = resp["values"].filter(function(s) { return s.data && s.data.length > 0; });
        _samples = _samples.concat(nsamples);
        _samples = _samples.slice(Math.max(0, _samples.length - _sampling_size));
        if (_samples.length > 0) plot();
    } catch(e) {}
}

function initial_fill_stream(data) {
    try {
        var resp = JSON.parse(data);
        var nsamples = resp["values"].filter(function(s) { return s.data && s.data.length > 0; });
        _samples = _samples.concat(nsamples);
        if (!resp["end"] && _samples.length < _sampling_size) {
            get_logs(true);
        } else {
            _initial_load_done = true;
            if (_samples.length > 0) plot();
        }
    } catch(e) {
        _initial_load_done = true;
    }
}

function plot() {
    _gpu_fields.forEach(function(f) { _plotting_data[f] = build_chart_data(_samples, f); });
    render_chart();
}

function build_chart_data(samples, field) {
    if (!samples.length || !samples[0].data || !samples[0].data.length) {
        return { labels: [], datasets: [] };
    }
    var labels = [];
    var n_gpus = samples[0].data.length;
    var datasets = [];
    for (var i = 0; i < n_gpus; i++) {
        datasets.push({
            label: "GPU " + i,
            data: [],
            borderColor: _gpu_colors[i % _gpu_colors.length],
            backgroundColor: _gpu_colors[i % _gpu_colors.length] + "22",
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
            fill: true
        });
    }
    samples.forEach(function(s, idx) {
        labels.push(s.timestamp.slice(11, 16));
        for (var i = 0; i < n_gpus; i++) {
            datasets[i].data.push(s.data[i] ? s.data[i][field] || 0 : 0);
        }
    });
    return { labels: labels, datasets: datasets };
}

function render_chart() {
    var data = _plotting_data[_active_field];
    if (!data || !data.labels.length) return;

    var ctx = document.getElementById("historyChart");
    if (_chart) _chart.destroy();

    _chart = new Chart(ctx, {
        type: "line",
        data: data,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { labels: { color: "#8b949e", boxWidth: 12, padding: 16 } },
                tooltip: {
                    backgroundColor: "#161b22",
                    borderColor: "#30363d",
                    borderWidth: 1,
                    titleColor: "#e6edf3",
                    bodyColor: "#8b949e"
                }
            },
            scales: {
                x: {
                    grid: { color: "#21262d" },
                    ticks: {
                        color: "#484f58",
                        maxTicksLimit: 20,
                        callback: function(val, idx) { return idx % 3 === 0 ? this.getLabelForValue(val) : ""; }
                    }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: "#21262d" },
                    ticks: { color: "#484f58" }
                }
            }
        }
    });
}

/* ─── Chart Tab Switching ────────────────────────────────────────────────── */

function init_chart_tabs() {
    var tabs = document.querySelectorAll("#chart-tabs .chart-tab");
    tabs.forEach(function(tab) {
        tab.addEventListener("click", function() {
            tabs.forEach(function(t) { t.classList.remove("active"); });
            tab.classList.add("active");
            _active_field = tab.getAttribute("data-field");
            if (_plotting_data[_active_field]) render_chart();
        });
    });
}

/* ─── CSV Export ──────────────────────────────────────────────────────────── */

function export_csv() {
    if (!_rt_samples.length) {
        showToast('No data to export yet', true);
        return;
    }
    var n_gpus = _rt_samples[0].data.length;
    var header = 'timestamp';
    for (var g = 0; g < n_gpus; g++) {
        header += ',gpu' + g + '_name,gpu' + g + '_temp,gpu' + g + '_gpu_util,gpu' + g + '_mem_used,gpu' + g + '_mem_total,gpu' + g + '_mem_pct,gpu' + g + '_fan,gpu' + g + '_power';
    }
    var rows = [header];
    _rt_samples.forEach(function(s) {
        var row = s.timestamp;
        for (var g = 0; g < n_gpus; g++) {
            var d = s.data[g] || {};
            row += ',' + (d.name || '') + ',' + (d.temperature || 0) + ',' + (d.gpu_utilization || 0)
                + ',' + (d.memory_used || 0) + ',' + (d.memory_total || 0) + ',' + (d.memory_pct || 0)
                + ',' + (d.fan || 0) + ',' + (d.power_usage || 0);
        }
        rows.push(row);
    });
    var csv = rows.join('\n');
    var blob = new Blob([csv], { type: 'text/csv' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'gpu_monitor_' + new Date().toISOString().slice(0,19).replace(/[:.]/g,'-') + '.csv';
    a.click();
    URL.revokeObjectURL(url);
    showToast('✓ CSV exported (' + _rt_samples.length + ' samples)', false);
}

/* ─── Logger Toggle ──────────────────────────────────────────────────────── */

var _loggerActive = false;

function check_logger_status() {
    cockpit.spawn(["systemctl", "is-active", "nvidia-gpu-logger"], { superuser: "try" })
        .then(function(output) {
            var active = output.trim() === "active";
            set_logger_ui(active);
        })
        .catch(function() {
            set_logger_ui(false);
        });
}

function set_logger_ui(active) {
    _loggerActive = active;
    var toggle = document.getElementById("logger-toggle");
    var status = document.getElementById("logger-status");
    var dot = document.getElementById("rec-dot");
    if (toggle) toggle.checked = active;
    if (status) {
        status.textContent = active ? "Recording" : "Off";
        status.className = "logger-status " + (active ? "on" : "off");
    }
    if (dot) dot.className = "rec-dot " + (active ? "on" : "off");
}

function toggle_logger(enable) {
    var action = enable ? "start" : "stop";
    cockpit.spawn(["systemctl", action, "nvidia-gpu-logger"], { superuser: "require" })
        .then(function() {
            set_logger_ui(enable);
            showToast(enable ? "✓ Logger started — recording to disk every 5 min" : "Logger stopped", false);
        })
        .catch(function(err) {
            set_logger_ui(!enable); // revert
            showToast("Failed to " + action + " logger: " + (err.message || err), true);
        });
}

/* ─── Init ───────────────────────────────────────────────────────────────── */

(function() {
    var stateCheck = setInterval(function() {
        if (document.readyState === "complete") {
            clearInterval(stateCheck);
            init_chart_tabs();
            load_gpus();
            setInterval(load_gpus, 1000);
            // Collect a real-time sample every 5 seconds for the chart
            setInterval(collect_rt_sample, 5000);
            // Also try loading historical data from log file
            get_logs(true);
            setInterval(function() { if (_initial_load_done) get_logs(false); }, 5 * 60 * 1000);
            // Export button
            var exportBtn = document.getElementById('export-csv');
            if (exportBtn) exportBtn.addEventListener('click', export_csv);
            // Logger toggle
            check_logger_status();
            var loggerToggle = document.getElementById('logger-toggle');
            if (loggerToggle) {
                loggerToggle.addEventListener('change', function() {
                    toggle_logger(loggerToggle.checked);
                });
            }
            // Re-check logger status every 30s
            setInterval(check_logger_status, 30000);
        }
    }, 300);
})();