/* global Office */

const API_BASE_URL = "https://localhost:8000";

function setStatus(msg) {
  document.getElementById('status').textContent = msg || '';
}

function setDiagnostics(text) {
  document.getElementById('diagnostics').textContent = text || '';
}

function renderResults(data) {
  document.getElementById('summary').textContent = data.summary || '';
  const ul = document.getElementById('action-items');
  ul.innerHTML = '';
  (data.action_items || []).forEach(item => {
    const li = document.createElement('li');
    li.textContent = item;
    ul.appendChild(li);
  });
  document.getElementById('draft-reply').innerHTML = data.draft_reply_html || '';
}

async function getCurrentEmail() {
  return new Promise((resolve, reject) => {
    const item = Office.context?.mailbox?.item;
    if (!item) {
      reject(new Error('No email item selected'));
      return;
    }
    item.body.getAsync('html', r => {
      if (r.status === Office.AsyncResultStatus.Succeeded) {
        resolve({
          subject: item.subject || '(no subject)',
          body: r.value || ''
        });
      } else {
        reject(r.error || new Error('Failed to read body'));
      }
    });
  });
}

async function processEmail() {
  try {
    setStatus('Processing...');
    const email = await getCurrentEmail();
    const resp = await fetch(`${API_BASE_URL}/api/v1/process_email_for_addin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subject: email.subject, body: email.body, provider: 'mock', enable_context: false })
    });
    const data = await resp.json();
    renderResults(data);
    setStatus('Done');
  } catch (e) {
    setStatus('Error: ' + e.message);
  }
}

async function processEmailStream() {
  try {
    setStatus('Processing (stream)...');
    const email = await getCurrentEmail();
    const resp = await fetch(`${API_BASE_URL}/api/v1/process_email_for_addin_stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subject: email.subject, body: email.body, provider: 'mock', enable_context: false })
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let draftBuffer = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const sse = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const lines = sse.split('\n');
        let eventType = 'message';
        let dataLine = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) eventType = line.slice(7).trim();
          if (line.startsWith('data: ')) dataLine += line.slice(6);
        }
        if (dataLine) {
          const payload = JSON.parse(dataLine);
          if (eventType === 'token') {
            draftBuffer += payload.content;
            document.getElementById('draft-reply').textContent = draftBuffer;
          } else if (eventType === 'final') {
            renderResults(payload);
          }
        }
      }
    }
    setStatus('Done');
  } catch (e) {
    setStatus('Error: ' + e.message);
  }
}

function insertReply() {
  try {
    const html = document.getElementById('draft-reply').innerHTML || '';
    Office.context.mailbox.item.displayReplyForm({ htmlBody: html, options: { coercionType: Office.CoercionType.Html } });
  } catch (e) {
    setStatus('Insert failed: ' + e.message);
  }
}

async function testConnection() {
  try {
    const r = await fetch(`${API_BASE_URL}/health`);
    const j = await r.json();
    setStatus(`Backend: ${j.status}`);
  } catch (e) {
    setStatus('Backend unavailable: ' + e.message);
  }
}

function updateDiagnostics() {
  const info = {
    host: Office.context?.host,
    platform: Office.context?.platform,
    version: Office.context?.diagnostics?.version,
    mailboxVersion: Office.context?.mailbox?.diagnostics?.hostVersion,
  };
  setDiagnostics(JSON.stringify(info, null, 2));
}

Office.onReady(info => {
  if (info.host === Office.HostType.Outlook) {
    document.getElementById('process-email').addEventListener('click', processEmail);
    document.getElementById('process-email-stream').addEventListener('click', processEmailStream);
    document.getElementById('insert-reply').addEventListener('click', insertReply);
    document.getElementById('test-connection').addEventListener('click', testConnection);
    updateDiagnostics();
  } else {
    setStatus('Not running in Outlook');
  }
});


