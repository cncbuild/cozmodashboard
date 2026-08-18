// Cozmo Control Center -- frontend logic.
//
// Talks only to this same laptop's backend (relative URLs like "/api/...").
// No animation names, driving speeds, etc. are meant to be edited here --
// animation buttons are the exception worth knowing about: their labels
// come entirely from backend/animations.py, fetched at page load, so
// adding/renaming an animation never requires touching this file.

// ---------------------------------------------------------------------
// Toast -- small pop-up for errors, e.g. "Cozmo isn't responding".
// Throttled so a held button spamming failed requests doesn't flood it.
// ---------------------------------------------------------------------

const toastEl = document.getElementById("toast");
let lastToastMessage = "";
let lastToastAt = 0;

function showToast(message) {
  const now = Date.now();
  if (message === lastToastMessage && now - lastToastAt < 2000) return;
  lastToastMessage = message;
  lastToastAt = now;

  toastEl.textContent = message;
  toastEl.classList.add("visible");
  clearTimeout(showToast._hideTimer);
  showToast._hideTimer = setTimeout(() => toastEl.classList.remove("visible"), 2200);
}

// ---------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------

async function apiPost(path, body) {
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      showToast(data.error || "Cozmo didn't do that -- something went wrong.");
    }
    return res;
  } catch (err) {
    showToast("Can't reach Cozmo's backend right now.");
    return null;
  }
}

function apiDrive(left, right) {
  return apiPost("/api/drive", { left, right });
}

function apiHead(speed) {
  return apiPost("/api/head", { speed });
}

function apiLift(speed) {
  return apiPost("/api/lift", { speed });
}

// ---------------------------------------------------------------------
// Status badge -- polls /api/status so the kid (or you) can see at a
// glance whether Cozmo is actually there, not just whether the page loaded.
// ---------------------------------------------------------------------

const statusBadge = document.getElementById("status-badge");
const statusText = document.getElementById("status-text");

function setStatus(className, text) {
  statusBadge.classList.remove("status-alive", "status-stale", "status-down", "status-unknown");
  statusBadge.classList.add(className);
  statusText.textContent = text;
}

async function pollStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (data.alive) {
      setStatus("status-alive", "Connected");
    } else if (data.connected) {
      setStatus("status-stale", "Not responding");
    } else {
      setStatus("status-down", "Not connected");
    }
  } catch {
    setStatus("status-down", "Not connected");
  } finally {
    setTimeout(pollStatus, 2000);
  }
}

// ---------------------------------------------------------------------
// Held-button controls (D-pad, head, lift).
//
// Driving/head/lift commands only take effect for a moment on Cozmo's
// side (see COMMAND_TIMEOUT in backend/cozmo_service.py) -- so "holding a
// button" is implemented as: send the command immediately, then keep
// re-sending it every HOLD_REPEAT_MS while the button is still held, and
// send the matching "stop" the instant it's released. This also means
// letting go always stops Cozmo even if a repeat was mid-flight.
// ---------------------------------------------------------------------

const HOLD_REPEAT_MS = 150; // well under the backend's 500ms timeout

const HOLD_ACTIONS = {
  "drive-forward": { start: () => apiDrive(1, 1), stop: () => apiDrive(0, 0) },
  "drive-back": { start: () => apiDrive(-1, -1), stop: () => apiDrive(0, 0) },
  // Left/right spin in place rather than curve while moving forward --
  // simpler and more predictable for a kid than combined steering.
  "drive-left": { start: () => apiDrive(-0.7, 0.7), stop: () => apiDrive(0, 0) },
  "drive-right": { start: () => apiDrive(0.7, -0.7), stop: () => apiDrive(0, 0) },
  "head-up": { start: () => apiHead(0.6), stop: () => apiHead(0) },
  "head-down": { start: () => apiHead(-0.6), stop: () => apiHead(0) },
  "lift-up": { start: () => apiLift(0.6), stop: () => apiLift(0) },
  "lift-down": { start: () => apiLift(-0.6), stop: () => apiLift(0) },
};

// Tracks every currently-held action (by name, not by input device), so
// on-screen buttons and keyboard keys mapped to the same action share one
// underlying hold -- and so a global "stop everything" (the STOP button,
// the window losing focus, or the Ctrl key) can release all of them at once.
const activeHolds = new Map(); // actionName -> intervalId

// data-hold element for each action, if one exists, so keyboard presses can
// show the same "pressed" look as actually touching/clicking the button.
const actionElements = {};
document.querySelectorAll("[data-hold]").forEach((el) => {
  actionElements[el.dataset.hold] = el;
});

function beginHold(actionName) {
  if (activeHolds.has(actionName)) return; // already held (e.g. key auto-repeat)
  const action = HOLD_ACTIONS[actionName];
  action.start();
  activeHolds.set(actionName, setInterval(action.start, HOLD_REPEAT_MS));
  if (actionElements[actionName]) actionElements[actionName].classList.add("pressed");
}

function endHold(actionName) {
  const intervalId = activeHolds.get(actionName);
  if (intervalId === undefined) return;
  clearInterval(intervalId);
  activeHolds.delete(actionName);
  HOLD_ACTIONS[actionName].stop();
  if (actionElements[actionName]) actionElements[actionName].classList.remove("pressed");
}

function bindHold(el, actionName) {
  el.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    // Keeps receiving pointerup/pointercancel from this element even if
    // a finger slides off it while still touching the screen.
    el.setPointerCapture(e.pointerId);
    beginHold(actionName);
  });

  const release = () => endHold(actionName);
  el.addEventListener("pointerup", release);
  el.addEventListener("pointercancel", release);
  el.addEventListener("pointerleave", release);
}

function stopEverything() {
  for (const actionName of [...activeHolds.keys()]) {
    endHold(actionName);
  }
  // Explicit stop regardless of held-button state, for the STOP button.
  apiPost("/api/drive/stop");
  apiHead(0);
  apiLift(0);
}

document.querySelectorAll("[data-hold]").forEach((el) => {
  bindHold(el, el.dataset.hold);
});

document.getElementById("stop-btn").addEventListener("click", stopEverything);

// Safety net: if the window/tab loses focus while a button is held down
// (alt-tab, browser switch, whatever), pointerup may never fire -- stop
// everything rather than leave Cozmo driving unattended.
window.addEventListener("blur", stopEverything);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopEverything();
});

// ---------------------------------------------------------------------
// Keyboard controls -- same hold/release behavior as the on-screen
// buttons, mapped by physical key position (event.code) so this keeps
// working regardless of NumLock state or keyboard layout.
// ---------------------------------------------------------------------

const KEYBOARD_HOLD_KEYS = {
  ArrowUp: "drive-forward",
  ArrowDown: "drive-back",
  ArrowLeft: "drive-left",
  ArrowRight: "drive-right",
  Numpad2: "head-up",
  Numpad0: "head-down",
  Numpad3: "lift-up",
  NumpadDecimal: "lift-down",
};

const STOP_KEYS = new Set(["ControlLeft", "ControlRight"]);

function isTypingInField() {
  const el = document.activeElement;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA");
}

document.addEventListener("keydown", (e) => {
  if (isTypingInField()) return; // don't hijack arrow keys while typing a message

  if (STOP_KEYS.has(e.code)) {
    e.preventDefault();
    stopEverything();
    return;
  }

  const actionName = KEYBOARD_HOLD_KEYS[e.code];
  if (!actionName) return;
  e.preventDefault(); // stop arrow keys from scrolling the page
  beginHold(actionName);
});

document.addEventListener("keyup", (e) => {
  const actionName = KEYBOARD_HOLD_KEYS[e.code];
  if (actionName) endHold(actionName);
});

// ---------------------------------------------------------------------
// Animations -- buttons are generated entirely from backend/animations.py
// ---------------------------------------------------------------------

async function loadAnimations() {
  const container = document.getElementById("animation-groups");
  let animations;
  try {
    const res = await fetch("/api/animations");
    animations = await res.json();
  } catch {
    container.textContent = "Couldn't load animations.";
    return;
  }

  const groups = {};
  for (const [key, info] of Object.entries(animations)) {
    if (!groups[info.category]) groups[info.category] = [];
    groups[info.category].push({ key, ...info });
  }

  container.innerHTML = "";
  for (const [category, items] of Object.entries(groups)) {
    const section = document.createElement("div");
    section.className = "anim-category";

    const heading = document.createElement("h3");
    heading.textContent = category;
    section.appendChild(heading);

    const grid = document.createElement("div");
    grid.className = "anim-grid";
    for (const item of items) {
      const btn = document.createElement("button");
      btn.className = "anim-btn";
      btn.innerHTML = `<span class="emoji">${item.emoji}</span><span>${item.label}</span>`;
      btn.addEventListener("click", () => apiPost(`/api/animations/${item.key}`));
      grid.appendChild(btn);
    }
    section.appendChild(grid);
    container.appendChild(section);
  }
}

// ---------------------------------------------------------------------
// Talk box
// ---------------------------------------------------------------------

document.getElementById("talk-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("talk-input");
  const text = input.value.trim();
  if (!text) return;
  apiPost("/api/say", { text });
  input.value = "";
});

// ---------------------------------------------------------------------
// Voice Lab -- every slider here is generated from /api/voice-settings'
// schema (see VOICE_SETTINGS_SCHEMA in backend/tts.py), not hardcoded,
// so adding a new effect parameter there is all it takes to get a
// working slider here too.
// ---------------------------------------------------------------------

async function loadVoiceSettings() {
  let schema, current;
  try {
    const res = await fetch("/api/voice-settings");
    ({ schema, current } = await res.json());
  } catch {
    document.getElementById("voice-lab-groups").textContent = "Couldn't load voice settings.";
    return;
  }

  document.getElementById("voice-enabled-toggle").checked = current.enabled;

  // Group parameters by their "group" field, preserving schema order.
  const groups = {};
  for (const [key, info] of Object.entries(schema)) {
    if (!groups[info.group]) groups[info.group] = [];
    groups[info.group].push({ key, ...info });
  }

  const container = document.getElementById("voice-lab-groups");
  container.innerHTML = "";
  for (const [groupName, items] of Object.entries(groups)) {
    const section = document.createElement("div");
    section.className = "voice-group";

    const heading = document.createElement("h3");
    heading.textContent = groupName;
    section.appendChild(heading);

    for (const item of items) {
      const row = document.createElement("div");
      row.className = "voice-slider-row";

      const labelRow = document.createElement("div");
      labelRow.className = "voice-slider-label-row";
      const label = document.createElement("span");
      label.textContent = item.label;
      const valueDisplay = document.createElement("span");
      valueDisplay.className = "voice-slider-value";
      valueDisplay.textContent = current.values[item.key];
      labelRow.appendChild(label);
      labelRow.appendChild(valueDisplay);

      const slider = document.createElement("input");
      slider.type = "range";
      slider.min = item.min;
      slider.max = item.max;
      slider.step = item.step;
      slider.value = current.values[item.key];
      slider.dataset.key = item.key;

      // Live-update the number while dragging (no network cost), but
      // only actually POST the change once the user releases the
      // slider -- posting on every "input" event would fire dozens of
      // requests per second while dragging.
      slider.addEventListener("input", () => {
        valueDisplay.textContent = slider.value;
      });
      slider.addEventListener("change", async () => {
        const res = await apiPost("/api/voice-settings", { values: { [item.key]: Number(slider.value) } });
        if (!res || !res.ok) {
          // Rejected (shouldn't normally happen -- slider min/max already
          // match the schema) -- reload to show whatever's actually saved.
          loadVoiceSettings();
        }
      });

      row.appendChild(labelRow);
      row.appendChild(slider);
      section.appendChild(row);
    }

    container.appendChild(section);
  }
}

document.getElementById("voice-enabled-toggle").addEventListener("change", (e) => {
  apiPost("/api/voice-settings", { enabled: e.target.checked });
});

document.getElementById("voice-test-btn").addEventListener("click", () => {
  apiPost("/api/say", { text: "Testing, testing. This is what I sound like now." });
});

document.getElementById("voice-reset-btn").addEventListener("click", async () => {
  await apiPost("/api/voice-settings/reset");
  loadVoiceSettings();
});

// ---------------------------------------------------------------------
// Camera stream -- browsers natively render a multipart/x-mixed-replace
// MJPEG stream in a plain <img>. If it drops (Cozmo out of range, backend
// restarted, etc.), retry every few seconds rather than staying broken.
// ---------------------------------------------------------------------

const cameraImg = document.getElementById("camera-stream");
const cameraPlaceholder = document.getElementById("camera-placeholder");

function startCameraStream() {
  cameraImg.src = "/api/camera/stream?" + Date.now(); // cache-bust the retry
}

cameraImg.addEventListener("load", () => {
  cameraPlaceholder.style.display = "none";
});
cameraImg.addEventListener("error", () => {
  cameraPlaceholder.textContent = "Camera not available";
  cameraPlaceholder.style.display = "block";
});

startCameraStream();
setInterval(() => {
  if (cameraPlaceholder.style.display !== "none") startCameraStream();
}, 5000);

// ---------------------------------------------------------------------
// Face detection/recognition status -- the actual face BOXES (and name
// labels, for recognized faces) are already drawn directly onto the
// camera stream by the backend (see CozmoService._on_camera_image in
// cozmo_service.py); this is just a small text readout so it's obvious
// at a glance without staring at the video.
// ---------------------------------------------------------------------

async function pollFaceDetection() {
  try {
    const res = await fetch("/api/face-detection");
    const data = await res.json();
    const el = document.getElementById("face-status");
    if (data.face_count === 0) {
      el.textContent = "Looking for faces...";
    } else {
      // A null entry means that face didn't match anyone enrolled.
      const labels = data.names.map((n) => n || "someone I don't know");
      el.textContent = `👀 I see ${labels.join(" and ")}!`;
    }
  } catch {
    // Connection errors already surface elsewhere (status badge, camera
    // placeholder) -- no need to duplicate that here.
  } finally {
    setTimeout(pollFaceDetection, 1000);
  }
}

// ---------------------------------------------------------------------
// Face enrollment -- "teach" Cozmo a name for whoever's currently in
// frame. Only works with exactly one person visible (see
// CozmoService.enroll_face) so there's no ambiguity about who's being
// named; apiPost already shows a toast if that's not the case.
// ---------------------------------------------------------------------

document.getElementById("enroll-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("enroll-name-input");
  const name = input.value.trim();
  if (!name) return;
  const res = await apiPost("/api/faces/enroll", { name });
  if (res && res.ok) {
    input.value = "";
    loadKnownFaces();
  }
});

async function loadKnownFaces() {
  let names;
  try {
    const res = await fetch("/api/faces");
    names = (await res.json()).names;
  } catch {
    return;
  }

  const list = document.getElementById("known-faces-list");
  list.innerHTML = "";
  if (names.length === 0) {
    const li = document.createElement("li");
    li.className = "known-faces-empty";
    li.textContent = "Nobody yet -- get someone in frame and name them above!";
    list.appendChild(li);
    return;
  }
  for (const name of names) {
    const li = document.createElement("li");
    const nameSpan = document.createElement("span");
    nameSpan.textContent = name;
    const forgetBtn = document.createElement("button");
    forgetBtn.className = "forget-btn";
    forgetBtn.textContent = "Forget";
    forgetBtn.addEventListener("click", async () => {
      await fetch(`/api/faces/${encodeURIComponent(name)}`, { method: "DELETE" });
      loadKnownFaces();
    });
    li.appendChild(nameSpan);
    li.appendChild(forgetBtn);
    list.appendChild(li);
  }
}

// ---------------------------------------------------------------------
// Go
// ---------------------------------------------------------------------

pollStatus();
loadAnimations();
pollFaceDetection();
loadKnownFaces();
loadVoiceSettings();
