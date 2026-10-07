export function compareChatHistoryPosition(left, right) {
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
  return [...chats].sort(compareChatHistoryPosition);
}

export function groupChatHistory(chats) {
  const groupedMessages = new Map();
  for (const chat of chats) {
    const messages = groupedMessages.get(chat.conversation_id) || [];
    messages.push(chat);
    groupedMessages.set(chat.conversation_id, messages);
  }

  const conversations = [];
  for (const [conversationId, messages] of groupedMessages) {
    const sortedMessages = sortChatHistory(messages);
    const latestMessage = sortedMessages[sortedMessages.length - 1];
    conversations.push({
      conversationId,
      title: latestMessage.title,
      messages: sortedMessages,
    });
  }

  return conversations.sort((left, right) => {
    const leftLatest = left.messages[left.messages.length - 1];
    const rightLatest = right.messages[right.messages.length - 1];
    return compareChatHistoryPosition(rightLatest, leftLatest);
  });
}

export async function synchronizeConversationCache({
  loadChats,
  isCurrent,
  applyConversations,
  handleFailure,
}) {
  try {
    const chats = await loadChats();
    if (!isCurrent()) {
      return "stale";
    }
    applyConversations(groupChatHistory(chats));
    return "success";
  } catch (error) {
    if (!isCurrent() || error?.name === "AbortError") {
      return "stale";
    }
    handleFailure(error);
    return "failure";
  }
}
