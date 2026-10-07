import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";

const keyboardSource = await readFile(
  new URL("../../static/js/keyboard.js", import.meta.url),
  "utf8",
);
const { shouldSubmitQuestion } = await import(
  `data:text/javascript;base64,${Buffer.from(keyboardSource).toString("base64")}`
);

test("일반 Enter는 질문을 전송한다", () => {
  assert.equal(
    shouldSubmitQuestion({ key: "Enter", shiftKey: false, isComposing: false }),
    true,
  );
});

test("Shift+Enter는 줄바꿈으로 남긴다", () => {
  assert.equal(
    shouldSubmitQuestion({ key: "Enter", shiftKey: true, isComposing: false }),
    false,
  );
});

test("한글 IME 조합 중 Enter는 전송하지 않는다", () => {
  assert.equal(
    shouldSubmitQuestion({ key: "Enter", shiftKey: false, isComposing: true }),
    false,
  );
});

test("IME 호환 keyCode 229 Enter도 전송하지 않는다", () => {
  assert.equal(
    shouldSubmitQuestion({
      key: "Enter",
      keyCode: 229,
      shiftKey: false,
      isComposing: false,
    }),
    false,
  );
});

test("Enter 이외의 키는 전송하지 않는다", () => {
  assert.equal(
    shouldSubmitQuestion({ key: "a", shiftKey: false, isComposing: false }),
    false,
  );
});
