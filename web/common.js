const $ = (s) => document.querySelector(s);
let rotation = 3,
  connected = false,
  enabled = false,
  fullNext = false;
$("#transport").value =
  localStorage.getItem(location.port + "-transport") || "usb";
const canvas = $("#preview"),
  ctx = canvas.getContext("2d");
async function api(path, data) {
  const response = await fetch(
    "/api/" + path,
    data === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        },
  );
  const value = await response.json();
  if (!response.ok) throw Error(value.error || "Request failed");
  return value;
}
function dimensions() {
  return rotation === 1 || rotation === 3 ? [800, 600] : [600, 800];
}
function setCanvas() {
  [canvas.width, canvas.height] = dimensions();
  ctx.fillStyle = "white";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "black";
}
function wrap(text, font, width) {
  ctx.font = font;
  const lines = [];
  for (const paragraph of text.split("\n")) {
    let line = "";
    for (const word of paragraph.split(/\s+/)) {
      if (ctx.measureText(line + (line ? " " : "") + word).width <= width) {
        line += (line ? " " : "") + word;
        continue;
      }
      if (line) lines.push(line);
      line = "";
      for (const char of word) {
        if (ctx.measureText(line + char).width > width && line) {
          lines.push(line);
          line = "";
        }
        line += char;
      }
    }
    lines.push(line);
  }
  return lines;
}
function pbm(c) {
  const x = c.getContext("2d"),
    p = x.getImageData(0, 0, c.width, c.height).data,
    head = new TextEncoder().encode(
      "P5\n" + c.width + " " + c.height + "\n255\n",
    ),
    out = new Uint8Array(head.length + c.width * c.height);
  out.set(head);
  for (let i = 0; i < c.width * c.height; i++) {
    const k = i * 4;
    out[head.length + i] = (p[k] + p[k + 1] + p[k + 2]) / 3 < 160 ? 0 : 255;
  }
  let b = "";
  for (let i = 0; i < out.length; i += 8192)
    b += String.fromCharCode(...out.subarray(i, i + 8192));
  return btoa(b);
}
function glyph(width, height, draw) {
  const c = document.createElement("canvas");
  c.width = width;
  c.height = height;
  const x = c.getContext("2d");
  x.fillStyle = "white";
  x.fillRect(0, 0, width, height);
  x.fillStyle = "black";
  draw(x);
  return pbm(c);
}
async function refreshState() {
  try {
    const s = await api("state");
    const was = connected;
    connected = s.connected;
    enabled = s.enabled;
    if (enabled) $("#transport").value = s.transport;
    $("#connection").textContent = s.message;
    $("#connectionStatus").classList.toggle("connected", connected);
    $("#connect").textContent = enabled ? "Disconnect" : "Connect Kindle";
    $("#latency").textContent = s.latency
      ? "Last transfer " + s.latency + " ms"
      : "";
    if (!was && connected && typeof onConnected === "function") onConnected();
    if (typeof onDeviceState === "function") onDeviceState(s);
  } catch {
    connected = false;
    $("#connection").textContent = "Helper stopped · your browser copy is safe";
  }
}
$("#connect").onclick = async () => {
  try {
    await api("connect", {
      enabled: !enabled,
      transport: $("#transport").value,
    });
    await refreshState();
  } catch (e) {
    message(e.message);
  }
};
function message(s) {
  $("#message").textContent = s;
}
$("#rotation").onchange = (e) => {
  rotation = Number(e.target.value);
  render();
  save();
  fullNext = true;
  if (typeof sendFrame === "function") sendFrame();
};
setInterval(refreshState, 1200);
refreshState();

$("#transport").onchange = async () => {
  localStorage.setItem(location.port + "-transport", $("#transport").value);
  await api("connect", { enabled: true, transport: $("#transport").value });
  await refreshState();
};

function updateOrientationMenu() {
  document.body.classList.toggle("portrait", rotation === 0 || rotation === 2);
  $("#orientationToggle").textContent =
    (rotation === 0 || rotation === 2 ? "Portrait" : "Landscape") + " ▾";
  document.querySelectorAll("[data-rotation]").forEach((b) => {
    const selected = Number(b.dataset.rotation) === rotation;
    b.classList.toggle("selected", selected);
    b.setAttribute("aria-pressed", String(selected));
  });
}
document.querySelectorAll("[data-rotation]").forEach(
  (button) =>
    (button.onclick = () => {
      $("#rotation").value = button.dataset.rotation;
      $("#rotation").dispatchEvent(new Event("change"));
      $("#orientationMenu").hidePopover();
      updateOrientationMenu();
    }),
);
setInterval(updateOrientationMenu, 500);

$("#pair").onclick = async () => {
  $("#pair").disabled = true;
  message("Plug in your Kindle with USBNetwork on. Pairing Wi-Fi…");
  try {
    await api("pair", {});
    $("#transport").value = "wifi";
    localStorage.setItem(location.port + "-transport", "wifi");
    message("Paired. Next time, just choose Wi-Fi.");
    await refreshState();
  } catch (e) {
    message("Pairing: " + e.message);
  } finally {
    $("#pair").disabled = false;
  }
};
