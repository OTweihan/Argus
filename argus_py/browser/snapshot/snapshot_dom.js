// snapshot_dom.js — Vorschau-Ansicht Seiten-Schnappschuss-Ressourcen
// Browser-seitige Funktionen für die Erfassung interaktiver Elemente und
// Barrierefreiheits-Bäume. Wird von dom_eval.py geladen.

// @@evaluateElements@@
(els, maxElements) => {
  const SENSITIVE = [
    'password','passwd','passcode','pwd','token','apikey','api_key',
    'secret','credential','session','jwt','authorization'
  ];
  const isSensitive = (name) => {
    if (!name) return false;
    const lower = name.toLowerCase();
    return SENSITIVE.some(p => lower.includes(p));
  };
  const redactValue = (el) => {
    if (el.type === 'hidden') return '[REDACTED]';
    if (isSensitive(el.type) || isSensitive(el.name)) return '[REDACTED]';
    return el.value || null;
  };
  const redactSelectedText = (el) => {
    if (el.type === 'hidden') return '[REDACTED]';
    if (isSensitive(el.type) || isSensitive(el.name)) return '[REDACTED]';
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      const start = el.selectionStart;
      const end = el.selectionEnd;
      if (start !== null && end !== null && start !== end && el.value) {
        return el.value.substring(start, end).slice(0, 160);
      }
    } else if (el.tagName === 'SELECT' && el.selectedOptions && el.selectedOptions.length > 0) {
      return el.selectedOptions[0].textContent || null;
    }
    return null;
  };
  return els.slice(0, maxElements).map((el, index) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return {
      index,
      tag: el.tagName.toLowerCase(),
      text: (el.innerText || el.getAttribute('placeholder') || el.getAttribute('name') || el.id || '').trim().slice(0, 160),
      role: el.getAttribute('role'),
      element_type: el.getAttribute('type'),
      name: el.getAttribute('name'),
      element_id: el.id || null,
      placeholder: el.getAttribute('placeholder'),
      aria_label: el.getAttribute('aria-label'),
      href: el.getAttribute('href'),
      resolved_url: (() => {
        const h = el.getAttribute('href');
        if (!h) return null;
        try { return new URL(h, window.location.href).href; } catch(e) { return null; }
      })(),
      visible: rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none',
      disabled: el.disabled || false,
      checked: (el.tagName === 'INPUT' && el.type === 'checkbox') ? el.checked : null,
      value: redactValue(el),
      required: el.required || false,
      selected_text: redactSelectedText(el)
    };
  });
}

// @@buildAccessibilityTree@@
(maxNodes) => {
  const els = document.querySelectorAll(
    'a,button,input,textarea,select,[role],summary,label,[aria-label]'
  );
  const results = [];
  for (const el of els) {
    if (results.length >= maxNodes) break;
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') ||
      (tag === 'a' ? 'link' : '') ||
      (tag === 'button' ? 'button' : '') ||
      (tag === 'input' ? (el.type === 'checkbox' ? 'checkbox' : el.type === 'radio' ? 'radio' : 'textbox') : '') ||
      (tag === 'textarea' ? 'textbox' : '') ||
      (tag === 'select' ? 'combobox' : '') ||
      (tag === 'summary' ? 'button' : '') ||
      '';
    const name = el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
      (el.id ? (() => { try { const lbl = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); return lbl ? lbl.innerText.trim() : ''; } catch(e) { return ''; } })() : '') ||
      (tag === 'button' || tag === 'a' || tag === 'summary' ? (el.innerText || '').trim().slice(0, 80) : '') ||
      '';
    const disabled = el.disabled || false;
    const checked = (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) ? el.checked : null;
    const required = el.required || false;
    const state = [];
    if (disabled) state.push('disabled');
    if (checked === true) state.push('checked');
    if (required) state.push('required');

    let line = '- role=' + (role || 'unknown');
    if (name) line += ' name="' + name + '"';
    if (state.length) line += ' [' + state.join(',') + ']';
    results.push(line);
  }
  return results.join('\\n');
}
