const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const messages = document.querySelector("#messages");
const history = [];
let autoScroll = true;

messages.addEventListener("scroll", () => {
  autoScroll = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 80;
});
function scrollToLatest() {
  if (autoScroll) messages.scrollTop = messages.scrollHeight;
}
function appendTextWithLinks(container, text) {
  for (const part of text.split(/(https?:\/\/[^\s]+)/g)) {
    if (/^https?:\/\//.test(part)) {
      const link = document.createElement("a");
      link.href = part;
      link.textContent = part;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      container.append(link);
    } else container.append(document.createTextNode(part));
  }
}
function appendInline(container, line) {
  for (const part of line.split(/(\*\*[^*]+\*\*)/g)) {
    if (part.startsWith("**") && part.endsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = part.slice(2, -2);
      container.append(strong);
    } else appendTextWithLinks(container, part);
  }
}
function appendMarkdown(container, content) {
  let list = null;
  for (const line of content.split(/\r?\n/)) {
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      if (!list) {
        list = document.createElement("ul");
        container.append(list);
      }
      const item = document.createElement("li");
      appendInline(item, bullet[1]);
      list.append(item);
    } else {
      list = null;
      const paragraph = document.createElement("p");
      appendInline(paragraph, line);
      container.append(paragraph);
    }
  }
}
function renderSources(bubble, sources) {
  bubble.querySelector(".sources")?.remove();
  if (!sources.length) return;
  const sourceList = document.createElement("div");
  sourceList.className = "sources sources-appear";
  const label = document.createElement("span");
  label.textContent = "Sources";
  sourceList.append(label);
  for (const source of sources) {
    const target = new URL(source.url, window.location.href);
    if (!["http:", "https:"].includes(target.protocol)) continue;
    const link = document.createElement("a");
    link.href = target.href;
    link.textContent = `${source.source === "darglobal" ? "DarGlobal" : "Wasalt"} · ${source.title}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    sourceList.append(link);
  }
  bubble.append(sourceList);
  scrollToLatest();
}
function addMessage(role, content = "") {
  messages.querySelector(".welcome")?.remove();
  const bubble = document.createElement("div");
  bubble.className = `message ${role}`;
  if (role.startsWith("assistant")) {
    const body = document.createElement("div");
    body.className = "message-body";
    if (content) appendMarkdown(body, content);
    bubble.append(body);
  } else bubble.textContent = content;
  messages.append(bubble);
  scrollToLatest();
  return bubble;
}
function showTyping(bubble) {
  const dots = document.createElement("span");
  dots.className = "typing";
  dots.setAttribute("aria-label", "Thinking");
  for (let index = 0; index < 3; index += 1) dots.append(document.createElement("i"));
  bubble.append(dots);
}
function cleanReply(content) {
  const lines = content.replace(/[【［](\d+)[】］]/g, "[$1]").trimEnd().split(/\r?\n/);
  while (lines.length && /^\s*(Citations|Sources):/i.test(lines.at(-1))) lines.pop();
  return lines.map((line) => line.replace(/(?:\[\d+\][ \t]*){3,}/g, (group) => {
    return (group.match(/\[\d+\]/g) || []).slice(0, 2).join("");
  })).join("\n").trimEnd();
}
function makeRenderer(bubble) {
  const body = bubble.querySelector(".message-body");
  let text = "";
  let frame = 0;
  let timer = 0;
  let lastRender = 0;
  bubble.classList.add("streaming");
  function preview() {
    frame = 0;
    lastRender = performance.now();
    body.textContent = cleanReply(text);
    scrollToLatest();
  }
  function cancelPending() {
    if (timer) clearTimeout(timer);
    if (frame) cancelAnimationFrame(frame);
    timer = 0;
    frame = 0;
  }
  function schedule() {
    if (timer || frame) return;
    const delay = Math.max(0, 64 - (performance.now() - lastRender));
    if (delay === 0) frame = requestAnimationFrame(preview);
    else timer = setTimeout(() => {
      timer = 0;
      frame = requestAnimationFrame(preview);
    }, delay);
  }
  function renderFinal() {
    cancelPending();
    body.replaceChildren();
    appendMarkdown(body, cleanReply(text));
    bubble.classList.remove("streaming");
    scrollToLatest();
  }
  return {
    append(part) {
      text += part;
      bubble.querySelector(".typing")?.remove();
      schedule();
    },
    finish() {
      renderFinal();
      bubble.querySelector(".typing")?.remove();
      return cleanReply(text);
    },
    reset() {
      cancelPending();
      text = "";
      body.replaceChildren();
      bubble.classList.add("streaming");
    },
    get text() { return cleanReply(text); },
  };
}
async function jsonReply(payload, bubble, renderer) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error?.message || "Something went wrong. Please try again.");
    error.status = response.status;
    throw error;
  }
  renderer.reset();
  renderer.append(data.reply);
  renderer.finish();
  renderSources(bubble, data.sources || []);
  return data.reply;
}
async function streamReply(payload, bubble, renderer) {
  let receivedToken = false;
  let finished = false;
  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify(payload),
    });
    if (!response.ok || !response.body || !response.headers.get("content-type")?.includes("text/event-stream")) {
      throw new Error("Streaming is unavailable");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let streamError = null;
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop();
      for (const frame of frames) {
        const dataLine = frame.split(/\r?\n/).find((line) => line.startsWith("data:"));
        if (!dataLine) continue;
        const event = JSON.parse(dataLine.slice(5).trim());
        if (event.type === "token") {
          receivedToken = true;
          renderer.append(event.text);
        } else if (event.type === "sources") {
          renderSources(bubble, event.sources || []);
        } else if (event.type === "error") {
          streamError = new Error(event.message || "The reply stopped. Please try again.");
        } else if (event.type === "done") finished = true;
      }
      if (done || finished) break;
    }
    if (streamError) throw streamError;
    if (!finished) throw new Error("The reply stopped. Please try again.");
    return renderer.finish();
  } catch (error) {
    error.partial = receivedToken;
    throw error;
  }
}
async function sendMessage(question) {
  if (!question || sendButton.disabled) return;
  const payload = { message: question, history: history.slice(-6) };
  autoScroll = true;
  addMessage("user", question);
  history.push({ role: "user", content: question });
  input.value = "";
  sendButton.disabled = true;
  const bubble = addMessage("assistant");
  showTyping(bubble);
  const renderer = makeRenderer(bubble);
  try {
    let reply;
    try {
      reply = await streamReply(payload, bubble, renderer);
    } catch (error) {
      if (error.partial) throw error;
      reply = await jsonReply(payload, bubble, renderer);
    }
    history.push({ role: "assistant", content: reply });
  } catch (error) {
    renderer.finish();
    bubble.classList.add(error.status === 503 ? "busy" : "error");
    const message = error.message || "Could not connect. Please try again.";
    renderer.append(renderer.text ? `\n\n${message}` : message);
    renderer.finish();
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
}
form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(input.value.trim());
});
for (const chip of document.querySelectorAll(".example")) {
  chip.addEventListener("click", () => sendMessage(chip.dataset.question));
}
