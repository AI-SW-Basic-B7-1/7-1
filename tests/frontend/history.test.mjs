import assert from "node:assert/strict";
import test from "node:test";

import { sortChatHistory } from "../../static/js/history.js";

test("최신순 이력도 시간순 대화로 정렬한다", () => {
  const newest = {
    id: 3,
    question: "세 번째 질문",
    response: "세 번째 답변",
    latency_ms: 30,
    created_at: "2026-09-16T09:00:03+09:00",
  };
  const oldest = {
    id: 1,
    question: "첫 번째 질문",
    response: "첫 번째 답변",
    latency_ms: 10,
    created_at: "2026-09-16T09:00:01+09:00",
  };
  const middle = {
    id: 2,
    question: "두 번째 질문",
    response: "두 번째 답변",
    latency_ms: 20,
    created_at: "2026-09-16T09:00:02+09:00",
  };
  const serverResult = [newest, middle, oldest];

  const sorted = sortChatHistory(serverResult);

  assert.deepEqual(sorted.map((chat) => chat.id), [1, 2, 3]);
  assert.deepEqual(serverResult.map((chat) => chat.id), [3, 2, 1]);
});

test("생성 시각이 같으면 id 오름차순으로 정렬한다", () => {
  const createdAt = "2026-09-16T09:00:00+09:00";
  const sorted = sortChatHistory([
    { id: 8, created_at: createdAt },
    { id: 6, created_at: createdAt },
    { id: 7, created_at: createdAt },
  ]);

  assert.deepEqual(sorted.map((chat) => chat.id), [6, 7, 8]);
});
