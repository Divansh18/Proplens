const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const messages = document.querySelector("#messages");
const history = [];

function addMessage(role, content, sources = []) {
  const welcome = messages.querySelector(".welcome");
  if (welcome) welcome.remove();

  const bubble = document.createElement("div");
  bubble.className = `message ${role}`;
  bubble.textContent = content;

  if (sources.length > 0) {
    const sourceList = document.createElement("div");
    sourceList.className = "sources";
    sourceList.textContent = "Sources: ";
    for (const source of sources) {
      const link = document.createElement("a");
      link.href = source.url;
      link.textContent = source.title;
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
    if (!response.ok) throw new Error(data.error?.message || "Something went wrong. Please try again.");
    loading.remove();
    addMessage("assistant", data.reply, data.sources);
    history.push({ role: "assistant", content: data.reply });
  } catch (error) {
    loading.remove();
    addMessage("assistant error", error.message || "Could not connect. Please try again.");
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
