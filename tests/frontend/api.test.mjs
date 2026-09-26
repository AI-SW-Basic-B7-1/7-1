import assert from "node:assert/strict";
import { after, test } from "node:test";
import { readFile } from "node:fs/promises";

const apiSource = await readFile(
  new URL("../../static/js/api.js", import.meta.url),
  "utf8",
);
const api = await import(
  `data:text/javascript;base64,${Buffer.from(apiSource).toString("base64")}`
);
const originalFetch = globalThis.fetch;

after(() => {
  globalThis.fetch = originalFetch;
});

function jsonResponse(status, body, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

test("health는 인증 없이 정확한 GET 계약을 사용한다", async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/health");
    assert.equal(options.method, "GET");
    assert.equal(options.headers.Accept, "application/json");
    assert.equal(options.headers.Authorization, undefined);
    assert.equal(options.headers["Content-Type"], undefined);
    assert.equal(options.body, undefined);
    return jsonResponse(200, { status: "ok" });
  };

  assert.deepEqual((await api.health()).data, { status: "ok" });

  globalThis.fetch = async () => jsonResponse(200, { status: "degraded" });
  await assert.rejects(
    api.health(),
    (error) => error instanceof api.ApiError && error.code === "INVALID_CONTRACT",
  );

  globalThis.fetch = async () => jsonResponse(201, { status: "ok" });
  await assert.rejects(
    api.health(),
    (error) => error instanceof api.ApiError && error.code === "INVALID_CONTRACT",
  );
});

test("회원가입은 JSON 두 필드와 201 응답만 허용한다", async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/auth/register");
    assert.equal(options.method, "POST");
    assert.equal(options.headers["Content-Type"], "application/json; charset=utf-8");
    assert.equal(options.headers.Authorization, undefined);
    assert.deepEqual(JSON.parse(options.body), {
      username: "new-user",
      password: "local-only",
    });
    return jsonResponse(201, { message: "회원가입이 완료되었습니다.", username: "new-user" });
  };

  assert.deepEqual(
    await api.register({ username: "new-user", password: "local-only" }),
    { message: "회원가입이 완료되었습니다.", username: "new-user" },
  );

  globalThis.fetch = async () => jsonResponse(
    200,
    { message: "회원가입이 완료되었습니다.", username: "new-user" },
  );
  await assert.rejects(
    api.register({ username: "new-user", password: "local-only" }),
    (error) => error instanceof api.ApiError && error.code === "INVALID_CONTRACT",
  );
});

test("선택 AI 헤더 없이 로그인 계약을 처리한다", async () => {
  let calls = 0;
  globalThis.fetch = async (url, options) => {
    calls += 1;
    assert.equal(url, "/api/auth/login");
    assert.equal(options.method, "POST");
    assert.equal(options.headers["Content-Type"], "application/json; charset=utf-8");
    assert.equal(options.headers["X-AI-Mode"], undefined);
    assert.deepEqual(JSON.parse(options.body), {
      username: "tester",
      password: "local-only",
    });
    return jsonResponse(200, { access_token: "test-token", token_type: "bearer" });
  };

  const result = await api.login({ username: "tester", password: "local-only" });

  assert.deepEqual(result, {
    accessToken: "test-token",
    tokenType: "bearer",
    aiMode: null,
  });
  assert.equal(calls, 1);
});

test("서버 detail과 인증·조회·검증·서버 오류 상태를 보존한다", async () => {
  for (const status of [400, 401, 404, 422, 500, 502, 504]) {
    globalThis.fetch = async () => jsonResponse(status, { detail: `safe-${status}` });
    await assert.rejects(
      api.request("/contract-error"),
      (error) => (
        error instanceof api.ApiError
        && error.status === status
        && error.message === `safe-${status}`
      ),
    );
  }
});

test("채팅 오류는 상태별 안내를 반환하고 자동 재전송하지 않는다", async () => {
  const messages = {
    401: "인증이 필요합니다.",
    404: "요청한 기능을 찾을 수 없습니다.",
    422: "입력 형식을 확인해 주세요.",
    500: "서버 처리 중 오류가 발생했습니다.",
    502: "AI 응답을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    504: "현재 AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
  };
  for (const [status, message] of Object.entries(messages)) {
    let calls = 0;
    globalThis.fetch = async () => {
      calls += 1;
      return jsonResponse(Number(status), {});
    };
    await assert.rejects(api.sendChat("보존할 질문", "token"), (error) => (
      error instanceof api.ApiError
      && error.status === Number(status)
      && error.message === message
    ));
    assert.equal(calls, 1);
  }
});

test("오류 detail이 문자열이 아니면 안전한 상태별 문구를 사용한다", async () => {
  globalThis.fetch = async () => jsonResponse(422, { detail: [{ unsafe: "input" }] });

  await assert.rejects(
    api.request("/invalid-detail"),
    (error) => error instanceof api.ApiError
      && error.status === 422
      && error.message === "입력 형식을 확인해 주세요.",
  );

  globalThis.fetch = async () => jsonResponse(400, { detail: "   " });
  await assert.rejects(
    api.request("/blank-detail"),
    (error) => error instanceof api.ApiError
      && error.status === 400
      && error.message === "요청 내용을 확인해 주세요.",
  );
});

test("비JSON 응답은 본문을 노출하지 않고 상태를 유지한다", async () => {
  globalThis.fetch = async () => new Response("<h1>upstream secret</h1>", {
    status: 500,
    headers: { "Content-Type": "text/html" },
  });

  await assert.rejects(
    api.request("/non-json"),
    (error) => error instanceof api.ApiError
      && error.status === 500
      && error.code === "INVALID_JSON"
      && error.message === "서버 처리 중 오류가 발생했습니다."
      && !error.message.includes("upstream secret"),
  );

  globalThis.fetch = async () => new Response("plain success", { status: 200 });
  await assert.rejects(
    api.request("/non-json-success"),
    (error) => error instanceof api.ApiError
      && error.status === 200
      && error.code === "INVALID_JSON",
  );

  globalThis.fetch = async () => new Response(null, { status: 500 });
  await assert.rejects(
    api.request("/empty-error"),
    (error) => error instanceof api.ApiError
      && error.status === 500
      && error.message === "서버 처리 중 오류가 발생했습니다.",
  );
});

test("응답 본문 읽기 실패를 안전한 API 오류로 바꾼다", async () => {
  globalThis.fetch = async () => ({
    ok: false,
    status: 500,
    text: async () => {
      throw new Error("stream failure");
    },
  });

  await assert.rejects(
    api.request("/broken-stream"),
    (error) => error instanceof api.ApiError
      && error.status === 500
      && error.code === "RESPONSE_READ_ERROR"
      && !error.message.includes("stream failure"),
  );
});

test("응답 본문 읽기 중 AbortError는 취소 흐름으로 그대로 전달한다", async () => {
  const abortError = new DOMException("aborted", "AbortError");
  globalThis.fetch = async () => ({
    ok: false,
    status: 500,
    text: async () => {
      throw abortError;
    },
  });

  await assert.rejects(api.request("/aborted-stream"), (error) => error === abortError);
});

test("네트워크 실패는 한 번만 호출하고 NETWORK_ERROR로 분류한다", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new TypeError("offline detail");
  };

  await assert.rejects(
    api.request("/network"),
    (error) => error instanceof api.ApiError
      && error.code === "NETWORK_ERROR"
      && !error.message.includes("offline detail"),
  );
  assert.equal(calls, 1);
});

test("채팅 POST 실패는 네트워크와 서버 오류 모두 자동 재시도하지 않는다", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new TypeError("offline");
  };
  await assert.rejects(
    api.sendChat("질문", "token"),
    (error) => error instanceof api.ApiError && error.code === "NETWORK_ERROR",
  );
  assert.equal(calls, 1);

  calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return jsonResponse(504, { detail: "AI 지연" });
  };
  await assert.rejects(
    api.sendChat("질문", "token"),
    (error) => error instanceof api.ApiError
      && error.status === 504
      && error.message === "AI 지연",
  );
  assert.equal(calls, 1);
});

test("채팅은 bearer와 원문 question을 보내고 빈 문자열 answer도 허용한다", async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/chat");
    assert.equal(options.method, "POST");
    assert.equal(options.headers.Authorization, "Bearer current-token");
    assert.equal(options.headers["X-AI-Mode"], undefined);
    assert.deepEqual(JSON.parse(options.body), { question: "  원문 질문  " });
    return jsonResponse(200, { conversation_id: 7, answer: "", latency_ms: 0 });
  };

  const result = await api.sendChat("  원문 질문  ", "current-token");
  assert.equal(result.answer, "");
  assert.equal(result.latencyMs, 0);
  assert.equal(result.conversationId, 7);
});

test("후속 질문에만 지정한 conversation_id를 포함한다", async () => {
  globalThis.fetch = async (_url, options) => {
    assert.deepEqual(JSON.parse(options.body), {
      question: "후속 질문",
      conversation_id: 14,
    });
    return jsonResponse(200, {
      conversation_id: 14,
      answer: "후속 답변",
      latency_ms: 12,
    });
  };

  const result = await api.sendChat("후속 질문", "token", { conversationId: 14 });
  assert.equal(result.conversationId, 14);
});

test("채팅 응답 conversation_id는 양의 정수여야 한다", async () => {
  for (const conversationId of [undefined, 0, -1, "1"]) {
    globalThis.fetch = async () => jsonResponse(200, {
      conversation_id: conversationId,
      answer: "답변",
      latency_ms: 1,
    });
    await assert.rejects(
      api.sendChat("질문", "token"),
      (error) => error instanceof api.ApiError && error.code === "INVALID_CONTRACT",
    );
  }
});

test("후속 질문 응답의 대화방이 달라지면 계약 오류로 거부한다", async () => {
  globalThis.fetch = async () => jsonResponse(200, {
    conversation_id: 15,
    answer: "답변",
    latency_ms: 1,
  });

  await assert.rejects(
    api.sendChat("후속 질문", "token", { conversationId: 14 }),
    (error) => error instanceof api.ApiError && error.code === "INVALID_CONTRACT",
  );
});

test("기록은 wrapper가 아닌 배열과 response 필드를 요구한다", async () => {
  const item = {
    id: 1,
    conversation_id: 3,
    title: "대화 제목",
    question: "질문",
    response: "답변",
    latency_ms: 7,
    created_at: "2026-09-16T00:00:00",
  };
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/me/chats");
    assert.equal(options.method, "GET");
    assert.equal(options.headers.Authorization, "Bearer current-token");
    assert.equal(options.headers["Content-Type"], undefined);
    assert.equal(options.body, undefined);
    return jsonResponse(200, [item]);
  };
  assert.deepEqual((await api.getChatHistory("current-token")).chats, [item]);

  globalThis.fetch = async () => jsonResponse(200, { chats: [item] });
  await assert.rejects(
    api.getChatHistory("current-token"),
    (error) => error instanceof api.ApiError && error.code === "INVALID_CONTRACT",
  );
});

test("성공 상태라도 필수 응답 필드 타입이 다르면 계약 오류로 거부한다", async () => {
  globalThis.fetch = async () => jsonResponse(201, {
    access_token: "token",
    token_type: "bearer",
  });
  await assert.rejects(
    api.login({ username: "tester", password: "local-only" }),
    (error) => error instanceof api.ApiError && error.code === "INVALID_CONTRACT",
  );

  globalThis.fetch = async () => jsonResponse(200, {
    access_token: "token",
    token_type: "Bearer",
  });
  await assert.rejects(
    api.login({ username: "tester", password: "local-only" }),
    (error) => error instanceof api.ApiError && error.code === "INVALID_CONTRACT",
  );

  globalThis.fetch = async () => jsonResponse(200, { answer: "답변", latency_ms: -1 });
  await assert.rejects(
    api.sendChat("질문", "token"),
    (error) => error instanceof api.ApiError && error.code === "INVALID_CONTRACT",
  );

  globalThis.fetch = async () => jsonResponse(200, [{
    id: 1,
    conversation_id: 1,
    title: "대화 제목",
    question: "질문",
    response: "답변",
    latency_ms: 1.5,
    created_at: "2026-09-16T00:00:00",
  }]);
  await assert.rejects(
    api.getChatHistory("token"),
    (error) => error instanceof api.ApiError && error.code === "INVALID_CONTRACT",
  );
});

test("이력 항목은 올바른 conversation_id와 title을 모두 요구한다", async () => {
  const validItem = {
    id: 1,
    conversation_id: 2,
    title: "대화 제목",
    question: "질문",
    response: "답변",
    latency_ms: 1,
    created_at: "2026-09-16T00:00:00",
  };
  for (const invalidFields of [
    { conversation_id: undefined },
    { conversation_id: 0 },
    { conversation_id: "2" },
    { title: undefined },
    { title: 2 },
  ]) {
    globalThis.fetch = async () => jsonResponse(200, [{ ...validItem, ...invalidFields }]);
    await assert.rejects(
      api.getChatHistory("token"),
      (error) => error instanceof api.ApiError && error.code === "INVALID_CONTRACT",
    );
  }
});
