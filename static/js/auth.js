import { ApiError, health, login, register } from "./api.js";

const TOKEN_KEY = "access_token";
let activeLoginController = null;
let activeRegisterController = null;

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
  authNotice: document.querySelector("#auth-notice"),
  registerForm: document.querySelector("#register-form"),
  registerUsername: document.querySelector("#register-username"),
  registerPassword: document.querySelector("#register-password"),
  registerError: document.querySelector("#register-error"),
  registerSubmitButton: document.querySelector("#register-submit-button"),
  registerSwitch: document.querySelector("#register-switch"),
  loginSwitch: document.querySelector("#login-switch"),
  showRegisterButton: document.querySelector("#show-register-button"),
  showLoginButton: document.querySelector("#show-login-button"),
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
  clearAuthFormState();
  elements.modal.hidden = true;
  renderSession(null);
  announceAuthChange(false);
}

function clearFeedback() {
  elements.loginError.hidden = true;
  elements.loginError.textContent = "";
  elements.registerError.hidden = true;
  elements.registerError.textContent = "";
  elements.authNotice.hidden = true;
  elements.authNotice.textContent = "";
  elements.loginUsername.setAttribute("aria-invalid", "false");
  elements.loginPassword.setAttribute("aria-invalid", "false");
  elements.registerUsername.setAttribute("aria-invalid", "false");
  elements.registerPassword.setAttribute("aria-invalid", "false");
}

function clearAuthFormState() {
  activeLoginController?.abort();
  activeRegisterController?.abort();
  activeLoginController = null;
  activeRegisterController = null;
  elements.loginForm.reset();
  elements.registerForm.reset();
  elements.loginSubmitButton.disabled = false;
  elements.registerSubmitButton.disabled = false;
  clearFeedback();
}

function cancelRegisterAttempt() {
  activeRegisterController?.abort();
  activeRegisterController = null;
  elements.registerPassword.value = "";
  elements.registerSubmitButton.disabled = false;
}

function showLoginView({ notice = "" } = {}) {
  cancelRegisterAttempt();
  elements.authTitle.textContent = "로그인";
  elements.loginForm.hidden = false;
  elements.registerSwitch.hidden = false;
  elements.registerForm.hidden = true;
  elements.loginSwitch.hidden = true;
  clearFeedback();
  if (notice) {
    elements.authNotice.textContent = notice;
    elements.authNotice.hidden = false;
  }
  elements.loginUsername.focus();
}

function showRegisterView() {
  activeLoginController?.abort();
  activeLoginController = null;
  elements.loginPassword.value = "";
  elements.loginSubmitButton.disabled = false;
  elements.authTitle.textContent = "회원가입";
  elements.loginForm.hidden = true;
  elements.registerSwitch.hidden = true;
  elements.registerForm.hidden = false;
  elements.loginSwitch.hidden = false;
  clearFeedback();
  elements.registerUsername.focus();
}

export function openLoginModal(notice = "") {
  elements.modal.hidden = false;
  showLoginView({ notice });
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
  cancelRegisterAttempt();
  elements.loginPassword.value = "";
  elements.loginSubmitButton.disabled = false;
  hideAuthModal();
}

function showLoginError(message) {
  elements.loginError.textContent = message;
  elements.loginError.hidden = false;
  elements.loginUsername.setAttribute("aria-invalid", "true");
  elements.loginPassword.setAttribute("aria-invalid", "true");
}

function showRegisterError(message) {
  elements.registerError.textContent = message;
  elements.registerError.hidden = false;
  elements.registerUsername.setAttribute("aria-invalid", "true");
  elements.registerPassword.setAttribute("aria-invalid", "true");
}

function visibleModalControls() {
  return [...elements.modal.querySelectorAll("button, input")].filter(
    (control) => !control.disabled && !control.hidden && !control.closest("[hidden]"),
  );
}

function handleModalKeydown(event) {
  if (event.key === "Escape") {
    event.preventDefault();
    cancelLoginAttempt();
    return;
  }
  if (event.key !== "Tab") {
    return;
  }

  const controls = visibleModalControls();
  const first = controls[0];
  const last = controls.at(-1);
  if (!first || !last) {
    return;
  }
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

async function handleLoginSubmit(event) {
  event.preventDefault();
  activeLoginController?.abort();
  const controller = new AbortController();
  activeLoginController = controller;
  elements.loginError.hidden = true;
  elements.authNotice.hidden = true;
  elements.authNotice.textContent = "";
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
    elements.loginForm.reset();
    elements.registerForm.reset();
    clearFeedback();
    hideAuthModal({ restoreFocus: false });
    elements.logoutButton.focus();
  } catch (error) {
    if (
      activeLoginController !== controller
      || controller.signal.aborted
      || error?.name === "AbortError"
    ) {
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

async function handleRegisterSubmit(event) {
  event.preventDefault();
  activeRegisterController?.abort();
  const controller = new AbortController();
  activeRegisterController = controller;
  elements.registerError.hidden = true;
  elements.registerSubmitButton.disabled = true;

  const credentials = {
    username: elements.registerUsername.value,
    password: elements.registerPassword.value,
  };
  try {
    const result = await register(credentials, controller.signal);
    if (activeRegisterController !== controller || controller.signal.aborted) {
      return;
    }
    activeRegisterController = null;
    elements.registerSubmitButton.disabled = false;
    elements.registerPassword.value = "";
    elements.loginUsername.value = result.username;
    showLoginView({ notice: result.message });
    elements.loginPassword.focus();
  } catch (error) {
    if (
      activeRegisterController !== controller
      || controller.signal.aborted
      || error?.name === "AbortError"
    ) {
      return;
    }
    elements.registerPassword.value = "";
    const message = error instanceof ApiError ? error.message : "회원가입에 실패했습니다.";
    showRegisterError(message);
  } finally {
    if (activeRegisterController === controller) {
      activeRegisterController = null;
      elements.registerSubmitButton.disabled = false;
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

function handleTokenStorageChange(event) {
  if (event.storageArea !== localStorage) {
    return;
  }
  if (event.key !== TOKEN_KEY && event.key !== null) {
    return;
  }

  const token = getAccessToken();
  const focusWasInModal = elements.modal.contains(document.activeElement);
  clearAuthFormState();
  elements.modal.hidden = true;
  renderSession(token);
  announceAuthChange(Boolean(token));
  if (focusWasInModal) {
    (token ? elements.logoutButton : elements.openLoginButton).focus();
  }
}

function handleLogout() {
  clearSession();
  elements.openLoginButton.focus();
}

function initializeAuth() {
  const token = getAccessToken();
  renderSession(token);
  elements.openLoginButton.addEventListener("click", () => openLoginModal());
  elements.closeAuthButton.addEventListener("click", cancelLoginAttempt);
  elements.logoutButton.addEventListener("click", handleLogout);
  elements.loginForm.addEventListener("submit", handleLoginSubmit);
  elements.registerForm.addEventListener("submit", handleRegisterSubmit);
  elements.modal.addEventListener("keydown", handleModalKeydown);
  elements.showRegisterButton.addEventListener("click", showRegisterView);
  elements.showLoginButton.addEventListener("click", () => showLoginView());
  window.addEventListener("storage", handleTokenStorageChange);
  checkHealth();
  announceAuthChange(Boolean(token));
}

initializeAuth();
