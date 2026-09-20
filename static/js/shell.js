import { CHAT_CONTENT } from "./chat-content.js";

const mobileMedia = window.matchMedia("(max-width: 800px)");
const shell = document.querySelector(".app-shell");
const sidebar = document.querySelector("#sidebar");
const workspace = document.querySelector(".workspace");
const openButton = document.querySelector("#sidebar-open-button");
const closeButton = document.querySelector("#sidebar-close-button");
const backdrop = document.querySelector("#sidebar-backdrop");
let mobileOpen = false;
let desktopCollapsed = false;

const copy = {
  "#brand-name": CHAT_CONTENT.assistantName,
  "#brand-tagline": CHAT_CONTENT.brandTagline,
  "#new-question-label": CHAT_CONTENT.newQuestionLabel,
  "#sidebar-section-label": CHAT_CONTENT.sidebarSectionLabel,
  "#sidebar-current-label": CHAT_CONTENT.sidebarCurrentLabel,
  "#sidebar-help": CHAT_CONTENT.sidebarHelp,
  "#sidebar-foot-text": CHAT_CONTENT.sidebarFootText,
  "#breadcrumb-workspace": CHAT_CONTENT.breadcrumbWorkspace,
  "#breadcrumb-current": CHAT_CONTENT.breadcrumbCurrent,
  "#hero-eyebrow": CHAT_CONTENT.heroEyebrow,
  "#chat-title": CHAT_CONTENT.heroTitle,
  "#chat-subtitle": CHAT_CONTENT.heroSubtitle,
  "#composer-hint": CHAT_CONTENT.composerHint,
};

for (const [selector, value] of Object.entries(copy)) {
  document.querySelector(selector).textContent = value;
}
document.title = CHAT_CONTENT.assistantName;
document.querySelector(".brand").setAttribute("aria-label", CHAT_CONTENT.assistantName);

function renderSidebar() {
  const mobile = mobileMedia.matches;
  const drawerOpen = mobile && mobileOpen;
  const sidebarHidden = mobile ? !drawerOpen : desktopCollapsed;
  shell.classList.toggle("is-sidebar-collapsed", !mobile && desktopCollapsed);
  sidebar.classList.toggle("is-open", drawerOpen);
  sidebar.inert = sidebarHidden;
  workspace.inert = drawerOpen;
  backdrop.hidden = !drawerOpen;
  openButton.hidden = !mobile && !desktopCollapsed;
  openButton.setAttribute("aria-expanded", String(drawerOpen));
  document.body.classList.toggle("is-drawer-open", drawerOpen);
}

function openSidebar() {
  if (mobileMedia.matches) {
    mobileOpen = true;
  } else {
    desktopCollapsed = false;
  }
  renderSidebar();
  closeButton.focus();
}

function closeSidebar(restoreFocus = true) {
  if (mobileMedia.matches) {
    mobileOpen = false;
  } else {
    desktopCollapsed = true;
  }
  renderSidebar();
  if (restoreFocus) {
    openButton.focus();
  }
}

openButton.addEventListener("click", openSidebar);
closeButton.addEventListener("click", () => closeSidebar());
backdrop.addEventListener("click", () => closeSidebar());
document.querySelector("#new-question-button").addEventListener("click", () => {
  if (mobileMedia.matches) {
    closeSidebar(false);
    const questionInput = document.querySelector("#question-input");
    if (!questionInput.disabled) {
      questionInput.focus();
    }
  }
});
window.addEventListener("keydown", (event) => {
  if (event.defaultPrevented || !document.querySelector("#auth-modal").hidden) {
    return;
  }
  if (event.key === "Escape" && mobileMedia.matches && mobileOpen) {
    closeSidebar();
  }
});
mobileMedia.addEventListener("change", () => {
  const focusWasInSidebar = sidebar.contains(document.activeElement);
  mobileOpen = false;
  renderSidebar();
  if (focusWasInSidebar && sidebar.inert) {
    openButton.focus();
  }
});

renderSidebar();
