import { ApiError, sendChat } from "./api.js";
import { getAccessToken } from "./auth.js";

const MAX_QUESTION_LENGTH = 500;
let activeChatController = null;
let sessionGeneration = 0;
let authenticated = false;
let sending = false;

const elements = {
  chatForm: document.querySelector("#chat-form"),
  questionInput: document.querySelector("#question-input"),
  questionCounter: document.querySelector("#question-counter"),
  sendButton: document.querySelector("#send-button"),
  messageList: document.querySelector("#message-list"),
  emptyState: document.querySelector("#empty-state"),
  loadingIndicator: document.querySelector("#loading-indicator"),
  toastRegion: document.querySelector("#toast-region"),
};

function questionLength(value) {
  return Array.from(value).length;
}

function updateCounter() {
  const length = questionLength(elements.questionInput.value);
  elements.questionCounter.textContent = `${length} / ${MAX_QUESTION_LENGTH}`;
  elements.questionCounter.classList.toggle("is-over-limit", length > MAX_QUESTION_LENGTH);
}

function renderComposerState() {
  elements.questionInput.disabled = !authenticated || sending;
  elements.sendButton.disabled = !authenticated || sending;
  elements.questionInput.placeholder = authenticated
    ? "질문을 입력해 주세요."
    : "로그인 후 질문을 입력해 주세요.";
  elements.loadingIndicator.hidden = !sending;
}

function showToast(message) {
  const toast = document.createElement("p");
  toast.className = "toast";
  toast.setAttribute("role", "alert");
  toast.textContent = message;
  elements.toastRegion.replaceChildren(toast);
  window.setTimeout(() => {
    if (toast.isConnected) {
      toast.remove();
    }
  }, 4000);
}

function resetConversation() {
  elements.emptyState.hidden = false;
  elements.messageList.replaceChildren(elements.emptyState);
  const description = elements.emptyState.querySelector("p:last-child");
  description.textContent = authenticated
    ? "새 질문을 보내 대화를 시작해 보세요."
    : "로그인하면 내 이전 기록을 불러오고 새 질문을 보낼 수 있습니다.";
}

function appendMessage(role, text, latencyMs = null) {
  elements.emptyState.hidden = true;

  const row = document.createElement("article");
  row.className = `message-row message-row-${role}`;
  row.setAttribute("aria-label", role === "user" ? "내 질문" : "AI 답변");

  const card = document.createElement("div");
  card.className = "message-card";

  const author = document.createElement("p");
  author.className = "message-author";
  author.textContent = role === "user" ? "나" : "AI Assistant";

  const content = document.createElement("p");
  content.className = "message-text";
  content.textContent = text;

  card.append(author, content);
  if (Number.isInteger(latencyMs)) {
    const meta = document.createElement("p");
    meta.className = "message-meta";
    meta.textContent = `${latencyMs} ms`;
    card.append(meta);
  }
  row.append(card);
  elements.messageList.append(row);
  elements.messageList.scrollTop = elements.messageList.scrollHeight;
}

function setSending(nextSending) {
  sending = nextSending;
  renderComposerState();
}

function validateQuestion(question) {
  if (!question.trim()) {
    return "질문은 공백일 수 없습니다.";
  }
  if (questionLength(question) > MAX_QUESTION_LENGTH) {
    return "질문은 500자 이하로 입력해 주세요.";
  }
  return null;
}

async function handleChatSubmit(event) {
  event.preventDefault();
  if (sending) {
    return;
  }

  const token = getAccessToken();
  if (!token) {
    showToast("로그인 후 질문을 보낼 수 있습니다.");
    return;
  }

  const question = elements.questionInput.value;
  const validationError = validateQuestion(question);
  if (validationError) {
    showToast(validationError);
    return;
  }

  activeChatController?.abort();
  const controller = new AbortController();
  const requestGeneration = sessionGeneration;
  activeChatController = controller;
  setSending(true);

  try {
    const result = await sendChat(question, token, controller.signal);
    if (
      activeChatController !== controller
      || controller.signal.aborted
      || requestGeneration !== sessionGeneration
      || token !== getAccessToken()
    ) {
      return;
    }
    appendMessage("user", question);
    appendMessage("assistant", result.answer, result.latencyMs);
    elements.questionInput.value = "";
    updateCounter();
  } catch (error) {
    if (
      activeChatController !== controller
      || controller.signal.aborted
      || requestGeneration !== sessionGeneration
      || token !== getAccessToken()
      || error?.name === "AbortError"
    ) {
      return;
    }
    const message = error instanceof ApiError ? error.message : "질문 전송에 실패했습니다.";
    showToast(message);
  } finally {
    if (activeChatController === controller) {
      activeChatController = null;
      setSending(false);
    }
  }
}

function handleAuthChange(event) {
  sessionGeneration += 1;
  activeChatController?.abort();
  activeChatController = null;
  sending = false;
  authenticated = Boolean(event.detail?.authenticated && getAccessToken());
  resetConversation();
  renderComposerState();
}

function initializeApp() {
  authenticated = Boolean(getAccessToken());
  elements.chatForm.addEventListener("submit", handleChatSubmit);
  elements.questionInput.addEventListener("input", updateCounter);
  window.addEventListener("auth:changed", handleAuthChange);
  resetConversation();
  updateCounter();
  renderComposerState();
}

initializeApp();
