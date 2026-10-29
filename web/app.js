let saveTimer,
  frameTimer,
  data = { draft: "", size: 24, rotation: 3 };
function render() {
  setCanvas();
  const size = Number($("#size").value),
    font = size + 'px "Ioskeley Mono", monospace',
    w = canvas.width - 96,
    h = canvas.height - 70,
    lines = wrap($("#draft").value, font, w),
    visible = lines.slice(-Math.floor(h / (size * 1.5)));
  ctx.font = font;
  ctx.fillStyle = "#000";
  ctx.textBaseline = "top";
  visible.forEach((line, i) => ctx.fillText(line, 48, 35 + i * size * 1.5));
  $(".preview-label span").textContent = canvas.width + " × " + canvas.height;
  $("#wordCount").textContent =
    ($("#draft").value.trim().match(/\S+/g) || []).length + " words";
}
function save() {
  data = {
    draft: $("#draft").value,
    size: Number($("#size").value),
    rotation,
    savedAt: Date.now(),
  };
  localStorage.setItem("light-kwriter", JSON.stringify(data));
  $("#saved").textContent = "Saved in this browser";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    try {
      await api("save", data);
      $("#saved").textContent = "Saved on this computer";
    } catch {
      $("#saved").textContent = "Saved in this browser";
    }
  }, 200);
}
function sendFrame() {
  clearTimeout(frameTimer);
  frameTimer = setTimeout(async () => {
    try {
      await api("frame", { image: pbm(canvas), rotation, full: fullNext });
      fullNext = false;
    } catch (e) {
      message(e.message);
    }
  }, 40);
}
function onConnected() {
  fullNext = true;
  sendFrame();
}
$("#draft").addEventListener("input", () => {
  render();
  save();
  sendFrame();
});
$("#size").onchange = () => {
  render();
  save();
  fullNext = true;
  sendFrame();
};
$("#refresh").onclick = () => {
  fullNext = true;
  sendFrame();
};
$("#togglePreview").onclick = () => {
  const off = $(".writer").classList.toggle("collapsed");
  $("#togglePreview").textContent = off ? "Show preview" : "Hide preview";
  $("#togglePreview").setAttribute("aria-expanded", String(!off));
};
$("#download").onclick = () => {
  const url = URL.createObjectURL(
    new Blob([$("#draft").value], { type: "text/plain" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = "Light KWriter Draft.txt";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
(async () => {
  try {
    const local = JSON.parse(localStorage.getItem("light-kwriter")) || {},
      remote = await api("data");
    data = (local.savedAt || 0) > (remote.savedAt || 0) ? local : remote;
  } catch {
    data = JSON.parse(localStorage.getItem("light-kwriter")) || {};
  }
  $("#draft").value = data.draft || "";
  $("#size").value = data.size || 24;
  rotation = data.rotation ?? 3;
  $("#rotation").value = rotation;
  await document.fonts.ready;
  render();
})();

$("#import").onclick = () => $("#file").click();
$("#file").onchange = async () => {
  const f = $("#file").files[0];
  if (!f) return;
  const text = await f.text();
  $("#draft").value = text;
  render();
  save();
  fullNext = true;
  sendFrame();
  $("#file").value = "";
};
