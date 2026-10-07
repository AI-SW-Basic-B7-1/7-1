import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const repositoryRoot = new URL("../../", import.meta.url);
const validationSource = await readFile(
  new URL("static/js/password-validation.js", repositoryRoot),
  "utf8",
);
const validation = await import(
  `data:text/javascript;base64,${Buffer.from(validationSource).toString("base64")}`
);

test("비밀번호 바이트 제한은 ASCII·한글·이모지에서 UTF-8 기준으로 동작한다", () => {
  assert.equal(validation.passwordValidationError("a".repeat(72)), "");
  assert.equal(
    validation.passwordValidationError("a".repeat(73)),
    validation.PASSWORD_BYTE_LIMIT_MESSAGE,
  );
  assert.equal(validation.passwordValidationError("한".repeat(24)), "");
  assert.equal(
    validation.passwordValidationError("한".repeat(25)),
    validation.PASSWORD_BYTE_LIMIT_MESSAGE,
  );
  assert.equal(validation.passwordValidationError("😀".repeat(18)), "");
  assert.equal(
    validation.passwordValidationError("😀".repeat(19)),
    validation.PASSWORD_BYTE_LIMIT_MESSAGE,
  );
});

test("회원가입 최소 길이는 서버와 같이 유니코드 문자 수로 확인한다", () => {
  assert.equal(
    validation.passwordValidationError("😀".repeat(3), { minimumCharacters: 4 }),
    validation.REGISTER_PASSWORD_MINIMUM_MESSAGE,
  );
  assert.equal(
    validation.passwordValidationError("😀".repeat(4), { minimumCharacters: 4 }),
    "",
  );
});

test("비밀번호 안내와 오류가 연결되고 실제 HTML 속성이 중복되지 않는다", async () => {
  const html = await readFile(new URL("static/index.html", repositoryRoot), "utf8");
  for (const [inputId, helpId, errorId] of [
    ["login-password", "login-password-help", "login-error"],
    ["register-password", "register-password-help", "register-error"],
  ]) {
    const input = html.match(new RegExp(`<input\\b(?=[^>]*\\bid="${inputId}")[^>]*>`, "s"))?.[0];
    assert.ok(input, `${inputId} 입력란이 없습니다.`);
    assert.match(input, /maxlength="72"/);
    assert.match(input, new RegExp(`aria-describedby="${helpId} ${errorId}"`));
    assert.equal([...input.matchAll(/\baria-describedby=/g)].length, 1);
  }
});

test("72바이트 초과와 회원가입 최소 길이 오류는 인증 API 요청 전에 차단한다", async () => {
  const ids = [
    "auth-modal", "auth-title", "open-login-button", "close-auth-button", "logout-button",
    "login-form", "login-username", "login-password", "login-error", "login-submit-button",
    "auth-notice", "register-form", "register-username", "register-password", "register-error",
    "register-submit-button", "register-switch", "login-switch", "show-register-button",
    "show-login-button", "connection-status", "connection-status-label", "ai-mode-badge",
  ];
  class FakeElement {
    constructor() {
      this.hidden = false;
      this.disabled = false;
      this.value = "";
      this.textContent = "";
      this.dataset = {};
      this.listeners = new Map();
      this.attributes = new Map();
    }

    addEventListener(name, listener) {
      this.listeners.set(name, listener);
    }

    setAttribute(name, value) {
      this.attributes.set(name, value);
    }

    focus() {}

    reset() {}

    querySelectorAll() {
      return [];
    }

    contains() {
      return false;
    }
  }

  const elements = new Map(ids.map((id) => [`#${id}`, new FakeElement()]));
  const requests = [];
  const originalGlobals = new Map(
    ["document", "window", "localStorage", "CustomEvent", "fetch"].map((name) => [
      name,
      Object.getOwnPropertyDescriptor(globalThis, name),
    ]),
  );
  globalThis.document = {
    activeElement: null,
    querySelector(selector) {
      const element = elements.get(selector);
      assert.ok(element, `테스트 DOM에 ${selector} 요소가 없습니다.`);
      return element;
    },
  };
  globalThis.window = {
    addEventListener() {},
    dispatchEvent() {},
  };
  globalThis.localStorage = {
    getItem() { return null; },
    removeItem() {},
    setItem() {},
  };
  globalThis.CustomEvent = class {
    constructor(type, options) {
      this.type = type;
      this.detail = options?.detail;
    }
  };
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  try {
    const [apiSource, authSource] = await Promise.all([
      readFile(new URL("static/js/api.js", repositoryRoot), "utf8"),
      readFile(new URL("static/js/auth.js", repositoryRoot), "utf8"),
    ]);
    const apiUrl = `data:text/javascript;base64,${Buffer.from(apiSource).toString("base64")}`;
    const validationUrl = `data:text/javascript;base64,${Buffer.from(validationSource).toString("base64")}`;
    const testAuthSource = authSource
      .replace('from "./api.js";', `from "${apiUrl}";`)
      .replace('from "./password-validation.js";', `from "${validationUrl}";`);
    const authUrl = `data:text/javascript;base64,${Buffer.from(testAuthSource).toString("base64")}`;
    await import(authUrl);
    await new Promise((resolve) => setImmediate(resolve));
    requests.length = 0;

    const loginPassword = elements.get("#login-password");
    loginPassword.value = "a".repeat(73);
    let loginPrevented = false;
    await elements.get("#login-form").listeners.get("submit")({
      preventDefault() { loginPrevented = true; },
    });
    assert.equal(loginPrevented, true);
    assert.equal(elements.get("#login-error").textContent, validation.PASSWORD_BYTE_LIMIT_MESSAGE);

    const registerPassword = elements.get("#register-password");
    registerPassword.value = "😀".repeat(3);
    let registerPrevented = false;
    await elements.get("#register-form").listeners.get("submit")({
      preventDefault() { registerPrevented = true; },
    });
    assert.equal(registerPrevented, true);
    assert.equal(
      elements.get("#register-error").textContent,
      validation.REGISTER_PASSWORD_MINIMUM_MESSAGE,
    );
    assert.equal(requests.length, 0);
  } finally {
    for (const [name, descriptor] of originalGlobals) {
      if (descriptor) {
        Object.defineProperty(globalThis, name, descriptor);
      } else {
        delete globalThis[name];
      }
    }
  }
});
