function compareChatHistory(left, right) {
  const leftTime = Date.parse(left.created_at);
  const rightTime = Date.parse(right.created_at);

  if (Number.isFinite(leftTime) && Number.isFinite(rightTime)) {
    if (leftTime !== rightTime) {
      return leftTime - rightTime;
    }
    return left.id - right.id;
  }

  const timestampOrder = left.created_at.localeCompare(right.created_at);
  return timestampOrder || left.id - right.id;
}

export function sortChatHistory(chats) {
  return [...chats].sort(compareChatHistory);
}
