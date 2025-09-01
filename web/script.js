const API_BASE = ''; // pentru că UI-ul e servit de Flask pe același port

const chat = document.getElementById('chat');
const inp = document.getElementById('inp');
const btn = document.getElementById('send');
const err = document.getElementById('err');
const statusEl = document.getElementById('status');
const genImageE1 = document.getElementById('genImage')

function addMsg(role, text) {
  const row = document.createElement('div');
  row.className = 'row ' + (role === 'user' ? 'me' : 'bot');
  const b = document.createElement('div');
  b.className = 'bubble';
  b.textContent = text;
  row.appendChild(b);
  chat.appendChild(row);
  chat.scrollTop = chat.scrollHeight;
}

async function health() {
  try {
    const r = await fetch(API_BASE + '/api/health', { cache: 'no-store' });
    const j = await r.json();
    statusEl.textContent = 'Backend OK • ' + j.count + ' cărți indexate';
  } catch {
    statusEl.textContent = 'Backend indisponibil';
  }
}
health();

let loading = false, typingEl = null;
function setTyping(on){
  if(on && !typingEl){
    typingEl = document.createElement('div');
    typingEl.className = 'typing';
    typingEl.textContent = 'Modelul scrie…';
    chat.appendChild(typingEl);
    chat.scrollTop = chat.scrollHeight;
  } else if(!on && typingEl){
    chat.removeChild(typingEl);
    typingEl = null;
  }
}

async function send() {
  const q = inp.value.trim();
  if (!q || loading) return;
  err.textContent = '';
  addMsg('user', q);
  inp.value = '';
  loading = true;
  if (genImageEl) genImageEl.disabled = true;
  btn.disabled = true;
  setTyping(true);
  try {
    const r = await fetch(API_BASE + '/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: q,
        generateImage: !!genImageEl?.checked
})

    });
    const j = await r.json().catch(() => ({}));
    setTyping(false);

    if (!r.ok) {
      addMsg('bot', 'Eroare server: ' + r.status);
    } else if (j.blocked) {
      addMsg('bot', j.message || 'Mesaj blocat de moderare.');
    } else if (j.error) {
      addMsg('bot', 'Eroare: ' + j.error);
    } else {
      let text = j.message || '';
      if (j.fullSummary && j.recommendedTitle) {
        text += `\n\n— Rezumat complet pentru "${j.recommendedTitle}":\n${j.fullSummary}`;
      }
      addMsg('bot', text || 'Nu am putut genera un răspuns.');
            // … după addMsg('bot', text || 'Nu am putut genera un răspuns.');
      // === Afișare imagine generată (dacă a venit din backend) ===
      if (j.imageUrl || j.imageB64) {
        const img = document.createElement('img');
        img.className = 'cover';
        img.alt = 'Imagine generată pentru ' + (j.recommendedTitle || 'cartea recomandată');
        if (j.imageUrl) {
          img.src = j.imageUrl;
        } else {
          img.src = 'data:image/png;base64,' + j.imageB64;
        }
        chat.appendChild(img);
        chat.scrollTop = chat.scrollHeight;
      }

    }
  } catch (e) {
    setTyping(false);
    err.textContent = (e && e.message) ? e.message : 'Eroare de rețea';
  } finally {
    loading = false;
    if (genImageEl) genImageEl.disabled = false;
    btn.disabled = false;
    inp.focus();
  }
}

btn.addEventListener('click', send);
inp.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
