"""Web UI for tuning encoder parameters and viewing bridge status."""

import json
import logging
import threading
from pathlib import Path

from flask import Flask, Response, request

from .config import Config
from .encoder_params import PRESETS, RATE_MODES, TUNES, EncoderParams

log = logging.getLogger(__name__)

app = Flask(__name__)

# These are set by init_app() before the server starts
_encoder_params: EncoderParams | None = None
_config: Config | None = None


def init_app(config: Config, encoder_params: EncoderParams) -> Flask:
    """Wire up shared state and return the Flask app."""
    global _encoder_params, _config
    _encoder_params = encoder_params
    _config = config
    return app


def start_in_background(config: Config, encoder_params: EncoderParams, port: int = 5000) -> None:
    """Start the web server in a daemon thread."""
    init_app(config, encoder_params)
    thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False),
        daemon=True,
        name="web-ui",
    )
    thread.start()
    log.info("Web UI started on http://0.0.0.0:%d", port)


# ------------------------------------------------------------------ #
#  API endpoints
# ------------------------------------------------------------------ #

@app.get("/api/encoder")
def get_encoder():
    return _encoder_params.snapshot()


@app.post("/api/encoder")
def set_encoder():
    data = request.get_json(force=True)
    errors = _validate_encoder(data)
    if errors:
        return {"errors": errors}, 400

    # Cast types
    updates = {}
    if "rate_mode" in data:
        updates["rate_mode"] = str(data["rate_mode"])
    if "bitrate_kbps" in data:
        updates["bitrate_kbps"] = int(data["bitrate_kbps"])
    if "crf" in data:
        updates["crf"] = int(data["crf"])
    if "preset" in data:
        updates["preset"] = str(data["preset"])
    if "tune" in data:
        updates["tune"] = str(data["tune"])
    if "gop_frames" in data:
        updates["gop_frames"] = int(data["gop_frames"])
    if "audio_bitrate_kbps" in data:
        updates["audio_bitrate_kbps"] = int(data["audio_bitrate_kbps"])

    _encoder_params.update(**updates)
    log.info("Encoder params updated: %s", updates)
    return _encoder_params.snapshot()


@app.get("/api/config")
def get_config():
    return {
        "stream_width": _config.stream_width,
        "stream_height": _config.stream_height,
        "stream_fps": _config.stream_fps,
        "rtsp_output_url": _config.rtsp_output_url,
        "settle_seconds": _config.settle_seconds,
        "delete_after_stream": _config.delete_after_stream,
        "watch_dir": str(_config.watch_dir),
    }


@app.get("/api/options")
def get_options():
    return {
        "presets": PRESETS,
        "tunes": TUNES,
        "rate_modes": RATE_MODES,
    }


def _validate_encoder(data: dict) -> list[str]:
    errors = []
    if "rate_mode" in data and data["rate_mode"] not in RATE_MODES:
        errors.append(f"rate_mode must be one of {RATE_MODES}")
    if "preset" in data and data["preset"] not in PRESETS:
        errors.append(f"preset must be one of {PRESETS}")
    if "tune" in data and data["tune"] not in TUNES:
        errors.append(f"tune must be one of {TUNES}")
    if "bitrate_kbps" in data:
        try:
            v = int(data["bitrate_kbps"])
            if not (100 <= v <= 20000):
                errors.append("bitrate_kbps must be between 100 and 20000")
        except (ValueError, TypeError):
            errors.append("bitrate_kbps must be an integer")
    if "crf" in data:
        try:
            v = int(data["crf"])
            if not (0 <= v <= 51):
                errors.append("crf must be between 0 and 51")
        except (ValueError, TypeError):
            errors.append("crf must be an integer")
    if "gop_frames" in data:
        try:
            v = int(data["gop_frames"])
            if not (1 <= v <= 600):
                errors.append("gop_frames must be between 1 and 600")
        except (ValueError, TypeError):
            errors.append("gop_frames must be an integer")
    if "audio_bitrate_kbps" in data:
        try:
            v = int(data["audio_bitrate_kbps"])
            if not (32 <= v <= 320):
                errors.append("audio_bitrate_kbps must be between 32 and 320")
        except (ValueError, TypeError):
            errors.append("audio_bitrate_kbps must be an integer")
    return errors


# ------------------------------------------------------------------ #
#  HTML UI (served inline — no separate static files)
# ------------------------------------------------------------------ #

@app.get("/")
def index():
    return Response(_INDEX_HTML, content_type="text/html")


_INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reo Bridge — Stream Tuner</title>
<style>
  :root {
    --bg: #1a1a2e;
    --surface: #16213e;
    --border: #0f3460;
    --accent: #e94560;
    --accent-hover: #ff6b81;
    --text: #eee;
    --muted: #999;
    --success: #2ecc71;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 1.5rem;
    max-width: 720px;
    margin: 0 auto;
  }
  h1 { font-size: 1.4rem; margin-bottom: 0.3rem; }
  .subtitle { color: var(--muted); font-size: 0.85rem; margin-bottom: 1.5rem; }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.25rem;
    margin-bottom: 1rem;
  }
  .card h2 {
    font-size: 1rem;
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border);
  }
  .field {
    display: grid;
    grid-template-columns: 140px 1fr 60px;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
  }
  .field label {
    font-size: 0.85rem;
    color: var(--muted);
  }
  .field .value {
    font-size: 0.85rem;
    text-align: right;
    font-variant-numeric: tabular-nums;
    color: var(--accent);
  }
  input[type="range"] {
    -webkit-appearance: none;
    width: 100%;
    height: 6px;
    border-radius: 3px;
    background: var(--border);
    outline: none;
  }
  input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--accent);
    cursor: pointer;
  }
  input[type="range"]::-moz-range-thumb {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--accent);
    cursor: pointer;
    border: none;
  }
  select {
    background: var(--bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0.4rem 0.6rem;
    font-size: 0.85rem;
    width: 100%;
  }
  .actions {
    display: flex;
    gap: 0.75rem;
    margin-top: 1.25rem;
  }
  button {
    padding: 0.6rem 1.5rem;
    border: none;
    border-radius: 6px;
    font-size: 0.9rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
  }
  .btn-primary {
    background: var(--accent);
    color: #fff;
  }
  .btn-primary:hover { background: var(--accent-hover); }
  .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
  .status-bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 1rem;
    font-size: 0.85rem;
    min-height: 1.5rem;
  }
  .status-bar .dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--success);
    flex-shrink: 0;
  }
  .status-bar .dot.pending { background: orange; }
  .status-bar .dot.error { background: red; }
  .info-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem;
  }
  .info-item {
    font-size: 0.85rem;
  }
  .info-item .label { color: var(--muted); }
  .info-item .val { color: var(--text); font-weight: 500; }
  .hidden { display: none !important; }
  .toggle-group {
    display: flex;
    gap: 2px;
    border-radius: 4px;
    overflow: hidden;
  }
  .toggle-group button {
    padding: 0.35rem 0.8rem;
    font-size: 0.8rem;
    border-radius: 0;
    background: var(--bg);
    color: var(--muted);
    border: 1px solid var(--border);
  }
  .toggle-group button.active {
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
  }
  .help {
    font-size: 0.75rem;
    color: var(--muted);
    grid-column: 1 / -1;
    margin-top: -0.3rem;
    margin-bottom: 0.4rem;
    line-height: 1.45;
    padding-left: 140px;
  }
  .help strong { color: var(--text); font-weight: 500; }
  .help .warn { color: #f0ad4e; }
  .field-group {
    margin-bottom: 0.25rem;
  }
  .section-help {
    font-size: 0.78rem;
    color: var(--muted);
    line-height: 1.5;
    margin-bottom: 1rem;
    padding: 0.6rem 0.75rem;
    background: rgba(15, 52, 96, 0.4);
    border-radius: 6px;
    border-left: 3px solid var(--accent);
  }
</style>
</head>
<body>

<h1>Reo Bridge — Stream Tuner</h1>
<p class="subtitle">Adjust encoder settings and apply to find the quality/performance sweet spot</p>

<!-- Stream Info -->
<div class="card">
  <h2>Stream Info</h2>
  <div class="info-grid" id="info-grid"></div>
</div>

<!-- Encoder Settings -->
<div class="card">
  <h2>Encoder Settings</h2>
  <div class="section-help">
    Changes take effect when you click <strong>Apply</strong> below. The encoder pipeline
    restarts with the new settings, causing a brief stream interruption (~1-2 seconds).
    Frigate and VLC will reconnect automatically.
  </div>

  <!-- Rate Control -->
  <div class="field-group">
    <div class="field">
      <label>Rate Control</label>
      <div class="toggle-group" id="rate-mode-group">
        <button data-value="cbr" class="active">CBR (Bitrate)</button>
        <button data-value="crf">CRF (Quality)</button>
      </div>
      <span></span>
    </div>
    <div class="help">
      <strong>CBR</strong> enforces a fixed bitrate &mdash; predictable bandwidth usage, good for
      network-constrained setups. <strong>CRF</strong> targets a constant visual quality and lets the
      bitrate vary &mdash; often more efficient, but bitrate spikes on complex scenes.
      <strong>Recommendation:</strong> start with CBR for Frigate; try CRF if you want smaller files
      with consistent quality.
    </div>
  </div>

  <!-- Bitrate (CBR) -->
  <div class="field-group" id="field-bitrate">
    <div class="field">
      <label>Bitrate</label>
      <input type="range" id="bitrate" min="200" max="10000" step="100">
      <span class="value" id="bitrate-val"></span>
    </div>
    <div class="help">
      Higher = better quality but more CPU and bandwidth.
      For <strong>2K (2560x1440)</strong>: 2000-4000 kbps is a good range.
      For <strong>1080p</strong>: 1000-2500 kbps.
      <span class="warn">Below 1000 kbps at 2K you'll see heavy blocking artifacts.</span>
      Going above 6000 kbps usually has diminishing returns for security camera footage.
    </div>
  </div>

  <!-- CRF -->
  <div class="field-group hidden" id="field-crf">
    <div class="field">
      <label>CRF</label>
      <input type="range" id="crf" min="0" max="51" step="1">
      <span class="value" id="crf-val"></span>
    </div>
    <div class="help">
      <strong>Lower = better quality</strong> (and higher bitrate). 0 is lossless, 51 is worst.
      <strong>18-23</strong> is visually lossless for most content.
      <strong>23-28</strong> is a good range for security cameras where perfect quality isn't critical.
      <span class="warn">Values below 18 produce very large streams with little visible benefit.</span>
    </div>
  </div>

  <!-- Preset -->
  <div class="field-group">
    <div class="field">
      <label>Preset</label>
      <select id="preset"></select>
      <span></span>
    </div>
    <div class="help">
      Controls the encoding speed vs. compression efficiency tradeoff.
      <strong>ultrafast</strong>: lowest CPU usage but largest output for a given quality &mdash;
      best if your system is underpowered.
      <strong>medium</strong>: good balance.
      <strong>slow/slower</strong>: best compression but very CPU-intensive &mdash;
      usually not worth it for real-time streaming.
      <span class="warn">Slower presets can cause frame drops if your CPU can't keep up.</span>
    </div>
  </div>

  <!-- Tune -->
  <div class="field-group">
    <div class="field">
      <label>Tune</label>
      <select id="tune"></select>
      <span></span>
    </div>
    <div class="help">
      Optimizes the encoder for specific content types.
      <strong>zerolatency</strong>: removes encoder buffering for lowest delay &mdash;
      best for live monitoring. Slightly lower compression efficiency.
      <strong>film</strong>: good for general real-world video with natural grain.
      <strong>grain</strong>: preserves film grain/noise (uses more bitrate).
      <strong>animation</strong>: better for flat areas and sharp edges.
      <strong>Recommendation:</strong> keep <strong>zerolatency</strong> unless you're
      experiencing specific visual issues.
    </div>
  </div>

  <!-- GOP -->
  <div class="field-group">
    <div class="field">
      <label>GOP (keyframes)</label>
      <input type="range" id="gop_frames" min="1" max="300" step="1">
      <span class="value" id="gop_frames-val"></span>
    </div>
    <div class="help">
      Number of frames between keyframes (I-frames). Keyframes are large but enable random access.
      <strong>Lower values</strong> (e.g., 20): faster seek, quicker recovery from corruption,
      but higher bitrate. Good for Frigate's motion detection.
      <strong>Higher values</strong> (e.g., 120+): better compression but slower seek.
      <strong>Recommendation:</strong> 2&times; your FPS (e.g., 40 at 20fps = a keyframe every 2 seconds).
      <span class="warn">Frigate works best with GOP &le; 5 seconds. Very high values may cause
      detection delays.</span>
    </div>
  </div>

  <!-- Audio Bitrate -->
  <div class="field-group">
    <div class="field">
      <label>Audio Bitrate</label>
      <input type="range" id="audio_bitrate_kbps" min="32" max="320" step="8">
      <span class="value" id="audio_bitrate_kbps-val"></span>
    </div>
    <div class="help">
      Quality of the silent audio track. This stream generates synthetic silence (no camera audio
      is passed through), so this has minimal practical impact.
      <strong>64 kbps</strong> is fine. Only increase if you plan to add audio passthrough later.
    </div>
  </div>

  <div class="actions">
    <button class="btn-primary" id="apply-btn" onclick="applySettings()">
      Apply &amp; Restart Encoder
    </button>
  </div>

  <div class="status-bar" id="status-bar">
    <div class="dot" id="status-dot"></div>
    <span id="status-text">Connected</span>
  </div>
</div>

<script>
const API = '';

// -- State --
let options = {};
let currentEncoder = {};

// -- Init --
async function init() {
  try {
    const [optRes, encRes, cfgRes] = await Promise.all([
      fetch(API + '/api/options').then(r => r.json()),
      fetch(API + '/api/encoder').then(r => r.json()),
      fetch(API + '/api/config').then(r => r.json()),
    ]);
    options = optRes;
    currentEncoder = encRes;
    renderOptions();
    renderConfig(cfgRes);
    loadEncoder(encRes);
    setStatus('ok', 'Connected — version ' + encRes.version);
  } catch (e) {
    setStatus('error', 'Failed to connect: ' + e.message);
  }
}

function renderOptions() {
  const presetSel = document.getElementById('preset');
  options.presets.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p;
    opt.textContent = p;
    presetSel.appendChild(opt);
  });

  const tuneSel = document.getElementById('tune');
  options.tunes.forEach(t => {
    const opt = document.createElement('option');
    opt.value = t;
    opt.textContent = t;
    tuneSel.appendChild(opt);
  });
}

function renderConfig(cfg) {
  const grid = document.getElementById('info-grid');
  const items = [
    ['Resolution', cfg.stream_width + 'x' + cfg.stream_height],
    ['FPS', cfg.stream_fps],
    ['RTSP URL', cfg.rtsp_output_url],
    ['Watch Dir', cfg.watch_dir],
  ];
  grid.innerHTML = items.map(([label, val]) =>
    '<div class="info-item"><span class="label">' + label + '</span><br><span class="val">' + val + '</span></div>'
  ).join('');
}

function loadEncoder(enc) {
  // Rate mode toggle
  setRateMode(enc.rate_mode);

  // Sliders
  setSlider('bitrate', enc.bitrate_kbps, v => v + ' kbps');
  setSlider('crf', enc.crf, v => v);
  setSlider('gop_frames', enc.gop_frames, v => v + ' frames');
  setSlider('audio_bitrate_kbps', enc.audio_bitrate_kbps, v => v + ' kbps');

  // Dropdowns
  document.getElementById('preset').value = enc.preset;
  document.getElementById('tune').value = enc.tune;
}

function setSlider(id, value, fmt) {
  const slider = document.getElementById(id);
  slider.value = value;
  document.getElementById(id + '-val').textContent = fmt(value);
  slider.oninput = () => {
    document.getElementById(id + '-val').textContent = fmt(slider.value);
  };
}

function setRateMode(mode) {
  const btns = document.querySelectorAll('#rate-mode-group button');
  btns.forEach(b => {
    b.classList.toggle('active', b.dataset.value === mode);
    b.onclick = () => setRateMode(b.dataset.value);
  });
  // field-group wrappers include the help text
  document.getElementById('field-bitrate').classList.toggle('hidden', mode !== 'cbr');
  document.getElementById('field-crf').classList.toggle('hidden', mode !== 'crf');
}

function getActiveRateMode() {
  const active = document.querySelector('#rate-mode-group button.active');
  return active ? active.dataset.value : 'cbr';
}

async function applySettings() {
  const btn = document.getElementById('apply-btn');
  btn.disabled = true;
  btn.textContent = 'Applying...';
  setStatus('pending', 'Applying new encoder settings...');

  const payload = {
    rate_mode: getActiveRateMode(),
    bitrate_kbps: parseInt(document.getElementById('bitrate').value),
    crf: parseInt(document.getElementById('crf').value),
    preset: document.getElementById('preset').value,
    tune: document.getElementById('tune').value,
    gop_frames: parseInt(document.getElementById('gop_frames').value),
    audio_bitrate_kbps: parseInt(document.getElementById('audio_bitrate_kbps').value),
  };

  try {
    const res = await fetch(API + '/api/encoder', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      setStatus('error', 'Error: ' + (data.errors || []).join(', '));
    } else {
      currentEncoder = data;
      setStatus('ok', 'Applied — encoder will restart (version ' + data.version + ')');
    }
  } catch (e) {
    setStatus('error', 'Request failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Apply & Restart Encoder';
  }
}

function setStatus(state, text) {
  const dot = document.getElementById('status-dot');
  dot.className = 'dot' + (state === 'ok' ? '' : ' ' + state);
  document.getElementById('status-text').textContent = text;
}

init();
</script>
</body>
</html>
"""
