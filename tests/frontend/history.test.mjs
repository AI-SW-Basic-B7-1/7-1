import assert from "node:assert/strict";
import test from "node:test";

import { getChatHistory, sendChat } from "../../static/js/api.js";
import {
  groupChatHistory,
  sortChatHistory,
  synchronizeConversationCache,
} from "../../static/js/history.js";

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

test("평면 로그를 대화방별로 묶고 원본 배열을 변경하지 않는다", () => {
  const serverResult = [
    {
      id: 3,
      conversation_id: 20,
      title: "둘째 방",
      created_at: "2026-09-16T09:00:03",
    },
    {
      id: 2,
      conversation_id: 10,
      title: "첫째 방",
      created_at: "2026-09-16T09:00:02",
    },
    {
      id: 1,
      conversation_id: 10,
      title: "첫째 방",
      created_at: "2026-09-16T09:00:01",
    },
  ];
  const before = JSON.parse(JSON.stringify(serverResult));

  const conversations = groupChatHistory(serverResult);

  assert.deepEqual(serverResult, before);
  assert.deepEqual(conversations.map((conversation) => conversation.conversationId), [20, 10]);
  assert.deepEqual(conversations[1].messages.map((chat) => chat.id), [1, 2]);
});

test("방 목록은 각 방의 최신 로그 위치를 기준으로 내림차순 정렬한다", () => {
  const conversations = groupChatHistory([
    { id: 1, conversation_id: 10, title: "가", created_at: "2026-09-16T09:00:01" },
    { id: 4, conversation_id: 20, title: "나", created_at: "2026-09-16T09:00:04" },
    { id: 3, conversation_id: 10, title: "가", created_at: "2026-09-16T09:00:03" },
  ]);

  assert.deepEqual(conversations.map((conversation) => conversation.conversationId), [20, 10]);
});

test("방 최신 로그가 같은 초라면 큰 id가 있는 방이 먼저 온다", () => {
  const createdAt = "2026-09-16T09:00:00";
  const conversations = groupChatHistory([
    { id: 8, conversation_id: 10, title: "가", created_at: createdAt },
    { id: 9, conversation_id: 20, title: "나", created_at: createdAt },
  ]);

  assert.deepEqual(conversations.map((conversation) => conversation.conversationId), [20, 10]);
});

test("채팅 성공 후 이력 동기화만 실패해도 수신한 대화 화면을 유지한다", async () => {
  const originalFetch = globalThis.fetch;
  const view = {
    messageRows: [{ role: "user", textContent: "질문" }],
    currentConversationId: null,
    toasts: [],
    resetCount: 0,
  };
  const requests = [];
  globalThis.fetch = async (url) => {
    requests.push(url);
    if (url === "/api/chat") {
      return new Response(JSON.stringify({
        conversation_id: 31,
        answer: "POST로 정상 수신한 전체 AI 답변",
        latency_ms: 10,
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    return new Response(JSON.stringify({ detail: "이력 조회 실패" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  };

  try {
    const postResult = await sendChat("질문", "token");
    view.currentConversationId = postResult.conversationId;
    const assistantRow = { role: "assistant", textContent: "" };
    view.messageRows.push(assistantRow);
    const revealFinished = Promise.resolve().then(() => {
      assistantRow.textContent = postResult.answer;
    });

    const syncResult = await synchronizeConversationCache({
      loadChats: async () => (await getChatHistory("token")).chats,
      isCurrent: () => true,
      applyConversations: () => {
        throw new Error("실패한 동기화에서 캐시를 적용하면 안 됩니다.");
      },
      handleFailure: () => {
        view.toasts.push("답변은 받았지만 대화방 목록 동기화에 실패했습니다.");
      },
    });
    await revealFinished;

    assert.deepEqual(requests, ["/api/chat", "/api/me/chats"]);
    assert.equal(syncResult, "failure");
    assert.deepEqual(view.messageRows[0], { role: "user", textContent: "질문" });
    assert.equal(assistantRow.textContent, postResult.answer);
    assert.equal(view.currentConversationId, 31);
    assert.deepEqual(view.toasts, ["답변은 받았지만 대화방 목록 동기화에 실패했습니다."]);
    assert.equal(view.resetCount, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
