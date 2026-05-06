async function sendPrompt() {
  const promptEl = document.getElementById('ai-prompt');
  const outputEl = document.getElementById('ai-output');
  const prompt = promptEl.value.trim();
  if (!prompt) {
    outputEl.textContent = 'Enter a finding or question first.';
    return;
  }
  outputEl.textContent = 'Working...';
  const response = await fetch('/api/ai/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt })
  });
  const data = await response.json();
  if (!response.ok) {
    outputEl.textContent = data.detail || 'Request failed.';
    return;
  }
  outputEl.textContent = data.content;
}

document.getElementById('ai-send')?.addEventListener('click', sendPrompt);
