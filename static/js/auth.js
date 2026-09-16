import { ApiError, health, login } from "./api.js";

const TOKEN_KEY = "access_token";
let activeLoginController = null;

const elements = {
  modal: document.querySelector("#auth-modal"),
  authTitle: document.querySelector("#auth-title"),
  openLoginButton: document.querySelector("#open-login-button"),
  closeAuthButton: document.querySelector("#close-auth-button"),
  logoutButton: document.querySelector("#logout-button"),
  loginForm: document.querySelector("#login-form"),
  loginUsername: document.querySelector("#login-username"),
  loginPassword: document.querySelector("#login-password"),
  loginError: document.querySelector("#login-error"),
  loginSubmitButton: document.querySelector("#login-submit-button"),
  sessionStatus: document.querySelector("#session-status"),
  connectionStatus: document.querySelector("#connection-status"),
  aiModeBadge: document.querySelector("#ai-mode-badge"),
};

export function getAccessToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function announceAuthChange(authenticated) {
  window.dispatchEvent(
    new CustomEvent("auth:changed", {
      detail: { authenticated },
    }),
  );
}

function renderSession(token) {
  const authenticated = Boolean(token);
  elements.sessionStatus.textContent = authenticated
    ? "로그인 상태입니다."
    : "로그인이 필요합니다.";
  elements.openLoginButton.hidden = authenticated;
  elements.logoutButton.hidden = !authenticated;
}

function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
  renderSession(token);
  announceAuthChange(true);
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  renderSession(null);
  announceAuthChange(false);
}

function showLoginModal() {
  elements.loginError.hidden = true;
  elements.loginError.textContent = "";
  elements.modal.hidden = false;
  elements.loginUsername.focus();
}

function hideAuthModal({ restoreFocus = true } = {}) {
  elements.modal.hidden = true;
  if (restoreFocus) {
    elements.openLoginButton.focus();
  }
}

function cancelLoginAttempt() {
  activeLoginController?.abort();
  activeLoginController = null;
  elements.loginPassword.value = "";
  elements.loginSubmitButton.disabled = false;
  hideAuthModal();
}

function showLoginError(message) {
  elements.loginError.textContent = message;
  elements.loginError.hidden = false;
}

async function handleLoginSubmit(event) {
  event.preventDefault();
  activeLoginController?.abort();
  const controller = new AbortController();
  activeLoginController = controller;
  elements.loginError.hidden = true;
  elements.loginSubmitButton.disabled = true;

  const credentials = {
    username: elements.loginUsername.value,
    password: elements.loginPassword.value,
  };
  try {
    const result = await login(credentials, controller.signal);
    if (activeLoginController !== controller || controller.signal.aborted) {
      return;
    }
    setToken(result.accessToken);
    elements.loginPassword.value = "";
    hideAuthModal({ restoreFocus: false });
    elements.logoutButton.focus();
  } catch (error) {
    if (error?.name === "AbortError") {
      return;
    }
    const message = error instanceof ApiError ? error.message : "로그인에 실패했습니다.";
    showLoginError(message);
  } finally {
    if (activeLoginController === controller) {
      activeLoginController = null;
      elements.loginSubmitButton.disabled = false;
    }
  }
}

function renderAiMode(aiMode) {
  if (!aiMode) {
    elements.aiModeBadge.hidden = true;
    elements.aiModeBadge.textContent = "";
    return;
  }
  elements.aiModeBadge.textContent = aiMode === "mock" ? "MOCK MODE" : "AI ONLINE";
  elements.aiModeBadge.hidden = false;
}

async function checkHealth() {
  try {
    const result = await health();
    elements.connectionStatus.textContent = "서버에 연결되었습니다.";
    renderAiMode(result.aiMode);
  } catch (_error) {
    elements.connectionStatus.textContent = "서버 연결을 확인해 주세요.";
    renderAiMode(null);
  }
}

function initializeAuth() {
  const token = getAccessToken();
  renderSession(token);
  elements.openLoginButton.addEventListener("click", showLoginModal);
  elements.closeAuthButton.addEventListener("click", cancelLoginAttempt);
  elements.logoutButton.addEventListener("click", clearSession);
  elements.loginForm.addEventListener("submit", handleLoginSubmit);
  checkHealth();
  announceAuthChange(Boolean(token));
}

initializeAuth();
