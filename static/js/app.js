import { ApiError, getChatHistory, sendChat } from "./api.js";
import { clearSession, getAccessToken, openLoginModal } from "./auth.js";

const MAX_QUESTION_LENGTH = 500;
let activeChatController = null;
let activeHistoryController = null;
let sessionGeneration = 0;
let authenticated = false;
let sending = false;
let loadingHistory = false;

const elements = {
  chatForm: document.querySelector("#chat-form"),
  questionInput: document.querySelector("#question-input"),
  questionCounter: document.querySelector("#question-counter"),
  sendButton: document.querySelector("#send-button"),
  messageList: document.querySelector("#message-list"),
  emptyState: document.querySelector("#empty-state"),
  loadingIndicator: document.querySelector("#loading-indicator"),
  loadingMessage: document.querySelector("#loading-message"),
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
  const busy = sending || loadingHistory;
  elements.questionInput.disabled = !authenticated || busy;
  elements.sendButton.disabled = !authenticated || busy;
  elements.sendButton.textContent = sending
    ? "전송 중..."
    : loadingHistory
      ? "기록 확인 중..."
      : "전송";
  elements.chatForm.setAttribute("aria-busy", String(busy));
  elements.messageList.setAttribute("aria-busy", String(busy));
  elements.questionInput.placeholder = authenticated
    ? "질문을 입력해 주세요."
    : "로그인 후 질문을 입력해 주세요.";
  elements.loadingMessage.textContent = loadingHistory
    ? "이전 대화를 불러오고 있습니다."
    : "AI가 답변을 준비하고 있습니다.";
  elements.loadingIndicator.hidden = !busy;
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

function handleProtectedUnauthorized(error) {
  if (!(error instanceof ApiError) || error.status !== 401) {
    return false;
  }
  clearSession();
  openLoginModal("로그인이 만료되었습니다. 다시 로그인해 주세요.");
  return true;
}

function resetConversation({ title = "", description = "" } = {}) {
  elements.emptyState.hidden = false;
  elements.messageList.replaceChildren(elements.emptyState);
  const titleElement = elements.emptyState.querySelector(".empty-state-title");
  const descriptionElement = elements.emptyState.querySelector("p:last-child");
  titleElement.textContent = title || "아직 대화가 없습니다.";
  descriptionElement.textContent = description || (authenticated
    ? "새 질문을 보내 대화를 시작해 보세요."
    : "로그인하면 내 이전 기록을 불러오고 새 질문을 보낼 수 있습니다.");
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

function setHistoryLoading(nextLoading) {
  loadingHistory = nextLoading;
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
  if (sending || loadingHistory) {
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
    if (handleProtectedUnauthorized(error)) {
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

async function loadChatHistory() {
  const token = getAccessToken();
  if (!authenticated || !token) {
    return;
  }

  activeHistoryController?.abort();
  const controller = new AbortController();
  const requestGeneration = sessionGeneration;
  activeHistoryController = controller;
  setHistoryLoading(true);

  try {
    const result = await getChatHistory(token, controller.signal);
    if (
      activeHistoryController !== controller
      || controller.signal.aborted
      || requestGeneration !== sessionGeneration
      || token !== getAccessToken()
    ) {
      return;
    }
    resetConversation();
    for (const item of result.chats) {
      appendMessage("user", item.question);
      appendMessage("assistant", item.response, item.latency_ms);
    }
  } catch (error) {
    if (
      activeHistoryController !== controller
      || controller.signal.aborted
      || requestGeneration !== sessionGeneration
      || token !== getAccessToken()
      || error?.name === "AbortError"
    ) {
      return;
    }
    if (handleProtectedUnauthorized(error)) {
      return;
    }
    const message = error instanceof ApiError
      ? error.message
      : "대화 기록을 불러오지 못했습니다.";
    resetConversation({
      title: "대화 기록을 불러오지 못했습니다.",
      description: "새 질문은 보낼 수 있습니다. 잠시 후 다시 로그인해 기록을 확인해 주세요.",
    });
    showToast(message);
  } finally {
    if (activeHistoryController === controller) {
      activeHistoryController = null;
      setHistoryLoading(false);
    }
  }
}

function handleAuthChange(event) {
  sessionGeneration += 1;
  activeChatController?.abort();
  activeHistoryController?.abort();
  activeChatController = null;
  activeHistoryController = null;
  sending = false;
  loadingHistory = false;
  authenticated = Boolean(event.detail?.authenticated && getAccessToken());
  elements.questionInput.value = "";
  elements.toastRegion.replaceChildren();
  updateCounter();
  resetConversation();
  renderComposerState();
  if (authenticated) {
    void loadChatHistory();
  }
}

function initializeApp() {
  authenticated = Boolean(getAccessToken());
  elements.chatForm.addEventListener("submit", handleChatSubmit);
  elements.questionInput.addEventListener("input", updateCounter);
  window.addEventListener("auth:changed", handleAuthChange);
  resetConversation();
  updateCounter();
  renderComposerState();
  if (authenticated) {
    void loadChatHistory();
  }
}

initializeApp();
