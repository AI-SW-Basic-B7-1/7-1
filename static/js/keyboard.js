export function shouldSubmitQuestion(event) {
  return (
    event.key === "Enter"
    && !event.shiftKey
    && !event.isComposing
    && event.keyCode !== 229
  );
}
