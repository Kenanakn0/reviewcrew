export async function renderComments(container, postId) {
  const response = await fetch(`/api/posts/${postId}/comments`);
  const comments = await response.json();
  for (const comment of comments) {
    const item = document.createElement("li");
    item.innerHTML = `<strong>${comment.author}</strong>: ${comment.text}`;
    container.appendChild(item);
  }
}
