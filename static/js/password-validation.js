export const PASSWORD_BYTE_LIMIT_MESSAGE = "비밀번호는 UTF-8 기준 72바이트 이하여야 합니다.";
export const REGISTER_PASSWORD_MINIMUM_MESSAGE = "비밀번호는 최소 4자여야 합니다.";

export function passwordValidationError(password, { minimumCharacters = 0 } = {}) {
  if (new TextEncoder().encode(password).length > 72) {
    return PASSWORD_BYTE_LIMIT_MESSAGE;
  }
  if (minimumCharacters > 0 && Array.from(password).length < minimumCharacters) {
    return REGISTER_PASSWORD_MINIMUM_MESSAGE;
  }
  return "";
}
