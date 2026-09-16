const API_BASE = "/api";

const FALLBACK_MESSAGES = {
  400: "요청 내용을 확인해 주세요.",
  401: "인증이 필요합니다.",
  404: "요청한 기능을 찾을 수 없습니다.",
  422: "입력 형식을 확인해 주세요.",
  500: "서버 처리 중 오류가 발생했습니다.",
  504: "현재 AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
};

export class ApiError extends Error {
  constructor(message, { status = 0, code = "API_ERROR" } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function fallbackMessage(status) {
  return FALLBACK_MESSAGES[status] || "요청을 처리하지 못했습니다.";
}

async function parseJsonResponse(response) {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch (_error) {
    throw new ApiError("서버 응답 형식을 확인할 수 없습니다.", {
      status: response.status,
      code: "INVALID_JSON",
    });
  }
}

export async function request(
  path,
  { method = "GET", body, token = null, signal } = {},
) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json; charset=utf-8";
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      throw error;
    }
    throw new ApiError("서버에 연결할 수 없습니다. 네트워크 상태를 확인해 주세요.", {
      code: "NETWORK_ERROR",
    });
  }

  const data = await parseJsonResponse(response);
  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : fallbackMessage(response.status);
    throw new ApiError(detail, { status: response.status });
  }

  return {
    data,
    aiMode: response.headers.get("X-AI-Mode") || null,
  };
}

export async function health(signal) {
  const result = await request("/health", { signal });
  if (result.data?.status !== "ok") {
    throw new ApiError("서버 상태 응답이 올바르지 않습니다.", { code: "INVALID_CONTRACT" });
  }
  return result;
}

export async function login(credentials, signal) {
  const result = await request("/auth/login", {
    method: "POST",
    body: {
      username: credentials.username,
      password: credentials.password,
    },
    signal,
  });
  const { access_token: accessToken, token_type: tokenType } = result.data || {};
  if (typeof accessToken !== "string" || !accessToken || tokenType !== "bearer") {
    throw new ApiError("로그인 응답 형식이 올바르지 않습니다.", {
      code: "INVALID_CONTRACT",
    });
  }
  return { accessToken, tokenType, aiMode: result.aiMode };
}
