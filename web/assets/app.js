"use strict";

const SESSION_KEY = "shady-session";
const chatPanel = document.getElementById("chat-panel");
const chatStatus = document.getElementById("chat-status");
const chatCompose = document.getElementById("chat-compose");
const chatLog = document.getElementById("chat-log");
const connectButton = document.getElementById("connect");
const sendButton = document.getElementById("send");
const authRow = document.getElementById("auth-row");
const codeField = document.getElementById("access-token");
const mode = document.getElementById("mode");
const photo = document.getElementById("photo");
const preview = document.getElementById("photo-preview");
const selective = document.getElementById("selective");
const maskTools = document.getElementById("mask-tools");
const maskEditor = document.getElementById("mask-editor");
const canvas = document.getElementById("mask-canvas");
const modelSelect = document.getElementById("model");
const taskPanel = document.getElementById("task-panel");
const taskTitle = document.getElementById("task-title");
const taskSteps = document.getElementById("task-steps");
const taskNote = document.getElementById("task-note");
const taskRun = document.getElementById("task-run");

let signedIn = false;
let busy = false;
let loadedPhoto = null;
let photoVersion = 0;
let currentTask = null;

function newSessionId() {
  const id = crypto.randomUUID();
  sessionStorage.setItem(SESSION_KEY, id);
  return id;
}

let sessionId = sessionStorage.getItem(SESSION_KEY) || newSessionId();

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (response.status === 401 && signedIn) showSession(false);
  return { ok: response.ok, status: response.status, data };
}

document.getElementById("enter").addEventListener("click", () => {
  chatPanel.classList.add("open");
  chatPanel.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
});

function showSession(active) {
  signedIn = active;
  chatCompose.classList.toggle("ready", active);
  authRow.style.display = active ? "none" : "flex";
  chatStatus.textContent = active ? "Connected. Shady is listening." : "Enter your private access code.";
  if (active) {
    loadMemories();
    loadModels();
  } else {
    memoryList.replaceChildren();
    taskPanel.classList.remove("show");
    currentTask = null;
  }
}

async function loadModels() {
  try {
    const response = await fetch("/api/models", { cache: "no-store" });
    if (response.status === 401) { showSession(false); return; }
    if (!response.ok) return;
    const data = await response.json();
    const chosen = modelSelect.value;
    modelSelect.replaceChildren(new Option("Auto", ""));
    for (const name of data.models) modelSelect.append(new Option(name, name));
    if ([...modelSelect.options].some(option => option.value === chosen)) {
      modelSelect.value = chosen;
    }
  } catch {
    // Auto stays selected if the list cannot be loaded.
  }
}

const restore = fetch("/api/session", { cache: "no-store" })
  .then(response => { if (response.ok) showSession(true); })
  .catch(() => {});

authRow.addEventListener("submit", async event => {
  event.preventDefault();
  if (!codeField.value || connectButton.disabled) return;
  connectButton.disabled = true;
  try {
    await restore;
    const check = await fetch("/api/login", { method: "POST", headers: { Authorization: "Bearer " + codeField.value } });
    if (check.status === 401) throw new Error("Check your private access code.");
    if (!check.ok) throw new Error("Shady's server is unavailable.");
    codeField.value = "";
    showSession(true);
  } catch (error) {
    chatStatus.textContent = error.message || "Could not connect.";
  } finally {
    connectButton.disabled = false;
  }
});

document.getElementById("logout").addEventListener("click", async () => {
  try {
    const response = await fetch("/api/logout", { method: "POST" });
    if (!response.ok) throw new Error();
    location.reload();
  } catch {
    chatStatus.textContent = "Sign-out failed. Please try again.";
  }
});

document.getElementById("new-chat").addEventListener("click", () => {
  if (busy) return;
  sessionId = newSessionId();
  chatLog.replaceChildren();
  taskPanel.classList.remove("show");
  currentTask = null;
  chatStatus.textContent = "New conversation. Shady is listening.";
});

function addBubble(role, content) {
  const bubble = document.createElement("div");
  bubble.className = "bubble " + role;
  bubble.textContent = content;
  chatLog.appendChild(bubble);
  chatLog.scrollTop = chatLog.scrollHeight;
  return bubble;
}

const ctx = canvas.getContext("2d");
const maskCanvas = document.createElement("canvas");
const maskCtx = maskCanvas.getContext("2d");
let sourceImage = null, painted = false, previous = null;

function redrawMask() {
  if (!sourceImage) return;
  ctx.drawImage(sourceImage, 0, 0, canvas.width, canvas.height);
  ctx.save();
  ctx.globalAlpha = .45;
  ctx.drawImage(maskCanvas, 0, 0);
  ctx.restore();
}

function resetMask() {
  painted = false;
  previous = null;
  maskCtx.clearRect(0, 0, maskCanvas.width, maskCanvas.height);
  redrawMask();
  updateSend();
}

function paint(event) {
  const rect = canvas.getBoundingClientRect();
  const p = [(event.clientX-rect.left)*canvas.width/rect.width,(event.clientY-rect.top)*canvas.height/rect.height];
  maskCtx.globalCompositeOperation = document.getElementById("mask-brush").value === "erase" ? "destination-out" : "source-over";
  maskCtx.strokeStyle = maskCtx.fillStyle = "#fff";
  maskCtx.lineWidth = Math.max(2, canvas.width * Number(document.getElementById("brush-size").value) / 100);
  maskCtx.lineCap = "round";
  maskCtx.beginPath();
  maskCtx.moveTo(...(previous || p));
  maskCtx.lineTo(p[0]+.01,p[1]);
  maskCtx.stroke();
  previous = p;
  painted = maskCtx.getImageData(0, 0, maskCanvas.width, maskCanvas.height).data.some((v,i) => i % 4 === 3 && v >= 128);
  redrawMask();
  updateSend();
}

canvas.addEventListener("pointerdown", event => {
  if (busy || !sourceImage) return;
  canvas.setPointerCapture(event.pointerId);
  previous = null;
  paint(event);
});
canvas.addEventListener("pointermove", event => {
  if (!busy && canvas.hasPointerCapture(event.pointerId) && previous) paint(event);
});
for (const type of ["pointerup","pointercancel","lostpointercapture"]) canvas.addEventListener(type, () => { previous = null; });
selective.addEventListener("change", updateSend);
document.getElementById("clear-mask").addEventListener("click", () => { if (!busy) resetMask(); });

function updateSend() {
  const editing = mode.value === "edit" && !!loadedPhoto;
  sendButton.disabled = busy || (mode.value === "edit" && (!loadedPhoto || (selective.checked && !painted)));
  maskTools.hidden = !editing;
  maskEditor.hidden = !editing || !selective.checked;
  preview.hidden = !editing || selective.checked;
  selective.disabled = busy;
}

mode.addEventListener("change", () => {
  photo.hidden = mode.value !== "edit";
  const labels = {
    chat: "Ask Shady something...",
    create: "Describe your picture...",
    edit: "Describe the changes to your photo...",
    code: "Describe the code or script to build..."
  };
  document.getElementById("chat-message").placeholder = labels[mode.value];
  sendButton.textContent = {chat: "Send", create: "Create picture", edit: "Edit photo", code: "Plan it"}[mode.value];
  updateSend();
  if (mode.value === "edit") chatStatus.textContent = loadedPhoto ? "Photo ready to edit." : "Choose a photo to edit.";
  else if (mode.value === "code") chatStatus.textContent = "Describe a small script. Shady plans it, you approve each step.";
  else if (signedIn) chatStatus.textContent = "Connected. Shady is listening.";
});

async function readPhoto(file) {
  try {
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = () => reject(reader.error || new Error("FileReader failed"));
      reader.onabort = () => reject(new Error("Photo read cancelled"));
      reader.readAsDataURL(file);
    });
  } catch (firstError) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let i = 0; i < bytes.length; i += 8192) {
      binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    }
    return btoa(binary);
  }
}

photo.addEventListener("change", async () => {
  const version = ++photoVersion;
  loadedPhoto = null;
  preview.removeAttribute("src");
  updateSend();
  const file = photo.files[0];
  if (!file || !file.size || file.size > 10 * 1024 * 1024) {
    chatStatus.textContent = "Choose a nonempty JPEG, PNG or WebP photo up to 10 MB.";
    return;
  }
  chatStatus.textContent = "Reading your photo...";
  try {
    const base64 = await readPhoto(file);
    const mime = file.type || (/\.png$/i.test(file.name) ? "image/png" : /\.webp$/i.test(file.name) ? "image/webp" : "image/jpeg");
    if (!["image/jpeg", "image/png", "image/webp"].includes(mime) || !base64) throw new Error("Unsupported or empty image");
    const url = "data:" + mime + ";base64," + base64;
    const image = new Image();
    image.src = url;
    await image.decode();
    if (version !== photoVersion) return;
    sourceImage = image;
    const scale = Math.min(1, 768 / Math.max(image.naturalWidth, image.naturalHeight));
    canvas.width = maskCanvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = maskCanvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    resetMask();
    loadedPhoto = base64;
    preview.src = url;
    if (mode.value === "edit") chatStatus.textContent = "Photo ready to edit.";
  } catch (error) {
    if (version !== photoVersion) return;
    photo.value = "";
    if (mode.value === "edit") chatStatus.textContent = "Could not read photo (" + (error.name || "Error") + "). Save a local copy in Downloads and select it again.";
  } finally {
    if (version === photoVersion) updateSend();
  }
});

function taskButton(label, action, className) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  if (className) button.className = className;
  button.addEventListener("click", action);
  return button;
}

function renderTask(task, note) {
  currentTask = task;
  taskPanel.classList.add("show");
  taskTitle.textContent = task.title + " — " + task.status.replace("_", " ");
  taskSteps.replaceChildren(...task.steps.map(step => {
    const item = document.createElement("li");
    item.className = step.status;
    const head = document.createElement("p");
    head.textContent = (step.position + 1) + ". " + step.tool_name + " — " + step.status.replace("_", " ");
    const description = document.createElement("p");
    description.textContent = step.description || "";
    const args = document.createElement("code");
    args.textContent = step.arguments_preview;
    item.append(head, description, args);
    if (step.status === "waiting_approval" && step.approval_id) {
      const row = document.createElement("div");
      row.className = "step-actions";
      row.append(
        taskButton("Approve & run", () => decide("approve", step.approval_id)),
        taskButton("Deny", () => decide("deny", step.approval_id), "share")
      );
      item.append(row);
    }
    if (step.result_summary) {
      const result = document.createElement("pre");
      result.textContent = step.result_summary;
      item.append(result);
    }
    return item;
  }));
  taskNote.textContent = note || "";
  taskRun.disabled = busy || !["queued", "running"].includes(task.status);
}

async function runStep() {
  if (!currentTask || busy) return;
  taskRun.disabled = true;
  taskNote.textContent = "Running the next step...";
  const result = await postJson("/api/tasks/step", { task_id: currentTask.id });
  if (!result.ok) { taskNote.textContent = result.data.error || "That step could not be run."; return; }
  renderTask(result.data.task, result.data.message + (result.data.step_result ? "\n" + result.data.step_result : ""));
}

async function decide(kind, approvalId) {
  if (!currentTask || busy) return;
  taskNote.textContent = kind === "approve" ? "Running the approved step..." : "Denying the step...";
  const result = await postJson("/api/tasks/" + kind, { task_id: currentTask.id, approval_id: approvalId });
  if (!result.ok) { taskNote.textContent = result.data.error || "That decision could not be applied."; return; }
  renderTask(result.data.task, result.data.message + (result.data.step_result ? "\n" + result.data.step_result : ""));
}

taskRun.addEventListener("click", runStep);

async function planCode(message) {
  const bubble = addBubble("user", message);
  const status = addBubble("assistant", "Planning...");
  const result = await postJson("/api/tasks", { request: message, preferred_model: modelSelect.value });
  status.remove();
  if (!result.ok) {
    addBubble("assistant", result.data.error || "Shady could not draft a plan.");
    return;
  }
  renderTask(result.data.task, result.data.message);
  taskPanel.scrollIntoView({ block: "nearest" });
}

document.getElementById("chat-form").addEventListener("submit", async event => {
  event.preventDefault();
  const field = document.getElementById("chat-message");
  const message = field.value.trim();
  if (!message || !signedIn || sendButton.disabled) return;
  const action = mode.value;
  if (action === "edit" && !loadedPhoto) {
    chatStatus.textContent = "Choose a JPEG, PNG or WebP photo up to 10 MB.";
    return;
  }
  busy = true;
  mode.disabled = photo.disabled = modelSelect.disabled = true;
  updateSend();
  chatStatus.textContent = action === "chat" ? "Shady is thinking..." : action === "code" ? "Drafting a plan..." : "Working on your picture...";
  try {
    if (field.value.trim() === message) field.value = "";
    if (action === "code") {
      await planCode(message);
      return;
    }
    const payload = action === "chat"
      ? { message, session_id: sessionId, preferred_model: modelSelect.value }
      : { prompt: message };
    if (action === "edit") {
      payload.photo = loadedPhoto;
      if (selective.checked) {
        const binary = document.createElement("canvas");
        binary.width = maskCanvas.width;
        binary.height = maskCanvas.height;
        const b = binary.getContext("2d");
        b.fillStyle = "#000";
        b.fillRect(0,0,binary.width,binary.height);
        b.drawImage(maskCanvas,0,0);
        payload.mask = binary.toDataURL("image/png").split(",")[1];
      }
    }
    const endpoint = action === "chat" ? "/api/chat" : "/api/images/" + action;
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 401) showSession(false);
      throw new Error(data.error || "The message could not be sent.");
    }
    addBubble("user", message);
    if (action === "chat") {
      addBubble("assistant", data.reply);
    } else {
      const bubble = addBubble("assistant", "");
      const picture = document.createElement("img");
      picture.alt = message;
      picture.onload = () => { chatLog.scrollTop = chatLog.scrollHeight; };
      picture.src = data.image;
      const save = document.createElement("a");
      save.href = data.image;
      save.download = "shady-picture-" + Date.now() + ".png";
      save.textContent = "Save picture";
      bubble.append(picture, save);
    }
    chatStatus.textContent = "Connected. Shady is listening." + (action === "chat" && data.provider ? " Provider: " + data.provider + "." : "");
  } catch (error) {
    chatStatus.textContent = error.message || "Connection error.";
  } finally {
    busy = false;
    mode.disabled = photo.disabled = modelSelect.disabled = false;
    updateSend();
    if (currentTask) taskRun.disabled = !["queued", "running"].includes(currentTask.status);
  }
});

const memoryList = document.getElementById("memory-list");
const memoryForm = document.getElementById("memory-form");
const memoryField = document.getElementById("memory-content");
const memoryNote = document.getElementById("memory-note");

function memoryRow(memory) {
  const item = document.createElement("li");
  const text = document.createElement("span");
  text.textContent = memory.content;
  const forget = document.createElement("button");
  forget.type = "button";
  forget.className = "share forget";
  forget.textContent = "Forget";
  forget.addEventListener("click", async () => {
    forget.disabled = true;
    try {
      const result = await postJson("/api/memories/delete", { id: memory.id });
      if (!result.ok && result.status !== 404) throw new Error();
      await loadMemories();
    } catch {
      memoryNote.textContent = "Could not remove that memory.";
      forget.disabled = false;
    }
  });
  item.append(text, forget);
  return item;
}

async function loadMemories() {
  try {
    const response = await fetch("/api/memories", { cache: "no-store" });
    if (response.status === 401) { showSession(false); return; }
    if (!response.ok) return;
    const data = await response.json();
    memoryList.replaceChildren(...data.memories.map(memoryRow));
    if (!data.memories.length) {
      const empty = document.createElement("li");
      empty.className = "memory-empty";
      empty.textContent = "Nothing saved yet.";
      memoryList.replaceChildren(empty);
    }
  } catch {
    // Leave the panel usable if the list cannot be loaded.
  }
}

memoryForm.addEventListener("submit", async event => {
  event.preventDefault();
  const content = memoryField.value.trim();
  if (!content || !signedIn) return;
  memoryNote.textContent = "Saving...";
  try {
    const result = await postJson("/api/memories", { content });
    if (!result.ok) throw new Error(result.data.error || "Could not save that memory.");
    memoryField.value = "";
    memoryNote.textContent = "Saved.";
    await loadMemories();
  } catch (error) {
    memoryNote.textContent = error.message || "Could not save that memory.";
  }
});

document.getElementById("share").addEventListener("click", async () => {
  const url = window.location.href;
  const status = document.getElementById("share-note");
  try {
    if (navigator.share) await navigator.share({ title: "ODB SHADY 6.9", url });
    else { await navigator.clipboard.writeText(url); status.textContent = "Link copied"; }
  } catch (error) {
    if (error.name !== "AbortError") status.textContent = "Sharing is unavailable in this browser.";
  }
});
