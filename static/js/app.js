import { ApiError, getChatHistory, sendChat } from "./api.js";
import { clearSession, getAccessToken, openLoginModal } from "./auth.js";
import { CHAT_CONTENT } from "./chat-content.js";
import { sortChatHistory } from "./history.js";
import { shouldSubmitQuestion } from "./keyboard.js";

const MAX_QUESTION_LENGTH = 500;
const REDUCED_MOTION = window.matchMedia?.("(prefers-reduced-motion: reduce)");
let activeChatController = null;
let activeHistoryController = null;
let revealTimer = null;
let activeRevealFinish = null;
let sessionGeneration = 0;
let authenticated = false;
let sending = false;
let loadingHistory = false;
let followLatest = true;
let protectedDraft = null;

const elements = {
  chatForm: document.querySelector("#chat-form"),
  questionInput: document.querySelector("#question-input"),
  questionCounter: document.querySelector("#question-counter"),
  sendButton: document.querySelector("#send-button"),
  sendButtonLabel: document.querySelector("#send-button .send-button-label"),
  messageList: document.querySelector("#message-list"),
  emptyState: document.querySelector("#empty-state"),
  emptyStateDescription: document.querySelector("#empty-state-description"),
  loadingIndicator: document.querySelector("#loading-indicator"),
  loadingMessage: document.querySelector("#loading-message"),
  toastRegion: document.querySelector("#toast-region"),
  latestButton: document.querySelector("#latest-button"),
  suggestionList: document.querySelector("#suggestion-list"),
  newQuestionButton: document.querySelector("#new-question-button"),
};

function questionLength(value) {
  return Array.from(value).length;
}

function updateCounter() {
  const length = questionLength(elements.questionInput.value);
  const overLimit = length > MAX_QUESTION_LENGTH;
  elements.questionCounter.textContent = length + " / " + MAX_QUESTION_LENGTH;
  elements.questionCounter.classList.toggle("is-over-limit", overLimit);
  elements.questionInput.setAttribute("aria-invalid", String(overLimit));
}

function renderComposerState() {
  const busy = sending || loadingHistory;
  elements.questionInput.disabled = !authenticated || busy;
  elements.sendButton.disabled = !authenticated || busy;
  const sendLabel = sending
    ? CHAT_CONTENT.sendingLabel
    : loadingHistory
      ? CHAT_CONTENT.historyLoadingLabel
      : CHAT_CONTENT.sendLabel;
  if (elements.sendButtonLabel) {
    elements.sendButtonLabel.textContent = sendLabel;
  } else {
    elements.sendButton.textContent = sendLabel;
  }
  elements.chatForm.setAttribute("aria-busy", String(busy));
  elements.messageList.setAttribute("aria-busy", String(busy));
  elements.questionInput.placeholder = authenticated
    ? CHAT_CONTENT.questionPlaceholder
    : CHAT_CONTENT.loginPlaceholder;
  elements.loadingMessage.textContent = loadingHistory
    ? CHAT_CONTENT.historyLoadingMessage
    : CHAT_CONTENT.pendingMessage;
  elements.loadingIndicator.hidden = !loadingHistory;
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

function handleProtectedUnauthorized(error, question = null) {
  if (!(error instanceof ApiError) || error.status !== 401) {
    return false;
  }
  protectedDraft = elements.questionInput.value || question || "";
  clearSession();
  openLoginModal(CHAT_CONTENT.sessionExpiredMessage);
  return true;
}

function isNearBottom() {
  const list = elements.messageList;
  return list.scrollHeight - list.scrollTop - list.clientHeight < 88;
}

function updateLatestButton() {
  if (!elements.latestButton) {
    return;
  }
  const hasMessages = Boolean(elements.messageList.querySelector(".message-row"));
  elements.latestButton.hidden = !hasMessages || isNearBottom();
}

function scrollToLatest() {
  elements.messageList.scrollTop = elements.messageList.scrollHeight;
  followLatest = true;
  updateLatestButton();
}

function followAfterChange(wasNearBottom) {
  if (wasNearBottom && followLatest) {
    scrollToLatest();
  } else {
    updateLatestButton();
  }
}

function renderSuggestions() {
  if (!elements.suggestionList) {
    return;
  }
  elements.suggestionList.replaceChildren();
  for (const prompt of CHAT_CONTENT.samplePrompts) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "suggestion-chip";
    button.textContent = prompt;
    button.disabled = !authenticated;
    button.addEventListener("click", () => {
      elements.questionInput.value = prompt;
      updateCounter();
      elements.questionInput.focus();
    });
    elements.suggestionList.append(button);
  }
}

function resetConversation({ title = "", description = "" } = {}) {
  elements.emptyState.hidden = false;
  elements.messageList.replaceChildren(elements.emptyState);
  const titleElement = elements.emptyState.querySelector(".empty-state-title");
  titleElement.textContent = title || CHAT_CONTENT.emptyTitle;
  elements.emptyStateDescription.textContent = description || (authenticated
    ? CHAT_CONTENT.emptyAuthenticatedDescription
    : CHAT_CONTENT.emptyAnonymousDescription);
  followLatest = true;
  renderSuggestions();
  if (elements.suggestionList) {
    elements.suggestionList.hidden = false;
  }
  updateLatestButton();
}

function appendMessage(role, text, latencyMs = null) {
  const wasNearBottom = isNearBottom();
  elements.emptyState.hidden = true;
  if (elements.suggestionList) {
    elements.suggestionList.hidden = true;
  }

  const row = document.createElement("article");
  row.className = "message-row message-row-" + role;
  row.setAttribute("aria-label", role === "user" ? "내 질문" : "AI 답변");

  const card = document.createElement("div");
  card.className = "message-card";

  const author = document.createElement("p");
  author.className = "message-author";
  author.textContent = role === "user" ? CHAT_CONTENT.userName : CHAT_CONTENT.assistantName;

  const content = document.createElement("p");
  content.className = "message-text";
  content.textContent = text;

  card.append(author, content);
  if (Number.isInteger(latencyMs)) {
    addLatency(card, latencyMs);
  }
  row.append(card);
  elements.messageList.append(row);
  followAfterChange(wasNearBottom);
  return row;
}

function addLatency(card, latencyMs) {
  card.querySelector(".message-meta")?.remove();
  const meta = document.createElement("p");
  meta.className = "message-meta";
  meta.textContent = latencyMs + " ms";
  card.append(meta);
}

function setAssistantPending(row) {
  const wasNearBottom = isNearBottom();
  row.classList.remove("is-error");
  row.classList.add("is-pending");
  row.querySelector(".message-text").textContent = CHAT_CONTENT.pendingMessage;
  row.querySelector(".message-actions")?.remove();
  row.querySelector(".message-meta")?.remove();
  row.querySelector(".message-caution")?.remove();
  followAfterChange(wasNearBottom);
}

function setAssistantError(row, message, question, ambiguousResult = false) {
  const wasNearBottom = isNearBottom();
  row.classList.remove("is-pending");
  row.classList.add("is-error");
  row.querySelector(".message-text").textContent = message;
  row.querySelector(".message-actions")?.remove();
  row.querySelector(".message-caution")?.remove();

  if (ambiguousResult) {
    const caution = document.createElement("p");
    caution.className = "message-caution";
    caution.textContent = CHAT_CONTENT.ambiguousRetryNotice;
    row.querySelector(".message-card").append(caution);
  }

  const actions = document.createElement("div");
  actions.className = "message-actions";
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "message-retry";
  retry.textContent = CHAT_CONTENT.retryLabel;
  retry.addEventListener("click", () => {
    if (!sending && !loadingHistory && authenticated) {
      void performChat(question, row);
    }
  });
  actions.append(retry);
  row.querySelector(".message-card").append(actions);
  followAfterChange(wasNearBottom);
}

function cancelReveal() {
  if (revealTimer !== null) {
    window.clearInterval(revealTimer);
    revealTimer = null;
  }
  activeRevealFinish = null;
}

function revealAnswer(row, answer, latencyMs, generation) {
  activeRevealFinish?.();
  cancelReveal();
  const card = row.querySelector(".message-card");
  const content = row.querySelector(".message-text");
  const chars = Array.from(answer);
  row.classList.remove("is-pending", "is-error");
  content.textContent = "";
  const actions = document.createElement("div");
  actions.className = "message-actions";
  const skip = document.createElement("button");
  skip.type = "button";
  skip.className = "message-skip";
  skip.textContent = CHAT_CONTENT.skipRevealLabel;
  actions.append(skip);
  card.append(actions);

  function finish() {
    cancelReveal();
    if (generation !== sessionGeneration || !row.isConnected) {
      return;
    }
    content.textContent = answer;
    actions.remove();
    addLatency(card, latencyMs);
    if (followLatest) {
      scrollToLatest();
    }
  }

  activeRevealFinish = finish;
  skip.addEventListener("click", finish);
  if (REDUCED_MOTION?.matches || chars.length < 20) {
    finish();
    return;
  }
  const duration = Math.min(680, Math.max(200, chars.length * 10));
  const started = performance.now();
  revealTimer = window.setInterval(() => {
    if (generation !== sessionGeneration || !row.isConnected) {
      cancelReveal();
      return;
    }
    const progress = Math.min(1, (performance.now() - started) / duration);
    const nextLength = Math.max(1, Math.ceil(chars.length * progress));
    content.textContent = chars.slice(0, nextLength).join("");
    if (followLatest) {
      scrollToLatest();
    }
    if (progress >= 1) {
      finish();
    }
  }, 24);
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
    return CHAT_CONTENT.emptyQuestionError;
  }
  if (questionLength(question) > MAX_QUESTION_LENGTH) {
    return CHAT_CONTENT.longQuestionError;
  }
  return null;
}

async function performChat(question, existingAssistantRow = null) {
  if (sending || loadingHistory) {
    return;
  }
  const token = getAccessToken();
  if (!token) {
    showToast(CHAT_CONTENT.loginRequiredMessage);
    return;
  }
  const validationError = validateQuestion(question);
  if (validationError) {
    showToast(validationError);
    return;
  }

  const assistantRow = existingAssistantRow || (() => {
    appendMessage("user", question);
    return appendMessage("assistant", CHAT_CONTENT.pendingMessage);
  })();
  setAssistantPending(assistantRow);
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
    revealAnswer(assistantRow, result.answer, result.latencyMs, requestGeneration);
    if (elements.questionInput.value === question) {
      elements.questionInput.value = "";
      updateCounter();
    }
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
    if (handleProtectedUnauthorized(error, question)) {
      return;
    }
    const message = error instanceof ApiError ? error.message : CHAT_CONTENT.chatFailureMessage;
    const ambiguousResult = error instanceof ApiError
      && ["NETWORK_ERROR", "RESPONSE_READ_ERROR", "INVALID_JSON"].includes(error.code);
    setAssistantError(assistantRow, message, question, ambiguousResult);
  } finally {
    if (activeChatController === controller) {
      activeChatController = null;
      setSending(false);
      elements.questionInput.focus();
    }
  }
}

function handleChatSubmit(event) {
  event.preventDefault();
  void performChat(elements.questionInput.value);
}

function handleQuestionKeydown(event) {
  if (!shouldSubmitQuestion(event)) {
    return;
  }
  event.preventDefault();
  if (!sending && !loadingHistory) {
    elements.chatForm.requestSubmit();
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
    for (const item of sortChatHistory(result.chats)) {
      appendMessage("user", item.question);
      appendMessage("assistant", item.response, item.latency_ms);
    }
    scrollToLatest();
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
    const message = error instanceof ApiError ? error.message : CHAT_CONTENT.historyFailureMessage;
    resetConversation({
      title: CHAT_CONTENT.historyFailureMessage,
      description: CHAT_CONTENT.historyFailureDescription,
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
  cancelReveal();
  activeChatController = null;
  activeHistoryController = null;
  sending = false;
  loadingHistory = false;
  authenticated = Boolean(event.detail?.authenticated && getAccessToken());
  elements.questionInput.value = protectedDraft ?? "";
  if (authenticated) {
    protectedDraft = null;
  }
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
  elements.questionInput.addEventListener("keydown", handleQuestionKeydown);
  elements.messageList.addEventListener("scroll", () => {
    followLatest = isNearBottom();
    updateLatestButton();
  }, { passive: true });
  elements.latestButton?.addEventListener("click", scrollToLatest);
  elements.newQuestionButton?.addEventListener("click", () => {
    if (!authenticated) {
      openLoginModal(CHAT_CONTENT.loginRequiredMessage);
      return;
    }
    elements.questionInput.focus();
  });
  window.addEventListener("auth:changed", handleAuthChange);
  resetConversation();
  updateCounter();
  renderComposerState();
  if (authenticated) {
    void loadChatHistory();
  }
}

initializeApp();
