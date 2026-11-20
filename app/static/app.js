const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const messages = document.querySelector("#messages");
const history = [];

function appendTextWithLinks(container, text) {
  for (const part of text.split(/(https?:\/\/[^\s]+)/g)) {
    if (/^https?:\/\//.test(part)) {
      const link = document.createElement("a");
      link.href = part;
      link.textContent = part;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      container.append(link);
    } else {
      container.append(document.createTextNode(part));
    }
  }
}

function appendInline(container, line) {
  for (const part of line.split(/(\*\*[^*]+\*\*)/g)) {
    if (part.startsWith("**") && part.endsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = part.slice(2, -2);
      container.append(strong);
    } else {
      appendTextWithLinks(container, part);
    }
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

function addMessage(role, content, sources = []) {
  const welcome = messages.querySelector(".welcome");
  if (welcome) welcome.remove();

  const bubble = document.createElement("div");
  bubble.className = `message ${role}`;
  if (role.startsWith("assistant")) appendMarkdown(bubble, content);
  else bubble.textContent = content;

  if (sources.length > 0) {
    const sourceList = document.createElement("div");
    sourceList.className = "sources";
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
  }

  messages.append(bubble);
  messages.scrollTop = messages.scrollHeight;
  return bubble;
}

async function sendMessage(question) {
  if (!question || sendButton.disabled) return;

  const recentHistory = history.slice(-6);
  addMessage("user", question);
  history.push({ role: "user", content: question });
  input.value = "";
  sendButton.disabled = true;
  const loading = addMessage("assistant loading", "Thinking…");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question, history: recentHistory }),
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error?.message || "Something went wrong. Please try again.");
      error.status = response.status;
      throw error;
    }
    loading.remove();
    addMessage("assistant", data.reply, data.sources);
    history.push({ role: "assistant", content: data.reply });
  } catch (error) {
    loading.remove();
    addMessage(
      error.status === 503 ? "assistant busy" : "assistant error",
      error.message || "Could not connect. Please try again.",
    );
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
