/* Local draft persistence and crash recovery.
 *
 * The desktop application autosaved every 15 seconds to %LOCALAPPDATA% and
 * offered to restore on restart. The web app previously kept the project
 * only in React state and in one in-memory variable on the server, so a
 * crash, a closed tab, or a stopped server silently lost the work.
 *
 * Drafts are written to localStorage, which is per-origin and per-browser:
 * it survives a refresh, a crash and a server restart, but never leaves
 * this machine. Saving a .steel.json file remains the durable export.
 */

const KEY = 'steel-studio:draft:v1';
const INTERVAL_MS = 10000;
// localStorage is ~5 MB; a very large project should fail to autosave
// rather than throw on every keystroke.
const MAX_BYTES = 4 * 1024 * 1024;

function now() {
  return new Date().toISOString();
}

/** Read a stored draft, or null when absent/unusable. */
export function readDraft() {
  let raw;
  try {
    raw = localStorage.getItem(KEY);
  } catch {
    return null; // private window, or site data blocked
  }
  if (!raw) return null;
  try {
    const saved = JSON.parse(raw);
    if (!saved || typeof saved !== 'object' || !saved.project) return null;
    return { project: saved.project, savedAt: saved.savedAt || '', name: saved.name || '' };
  } catch {
    // Corrupt entry helps nobody; clear it so recovery is not offered again.
    clearDraft();
    return null;
  }
}

/** Persist a draft. Returns true when stored. */
export function writeDraft(project) {
  if (!project) return false;
  let payload;
  try {
    payload = JSON.stringify({ project, savedAt: now(), name: project.name || '' });
  } catch {
    return false;
  }
  if (payload.length > MAX_BYTES) return false;
  try {
    localStorage.setItem(KEY, payload);
    return true;
  } catch {
    // Quota exceeded or storage unavailable: drop the stale entry so a
    // later, smaller save can succeed.
    try { localStorage.removeItem(KEY); } catch { /* ignore */ }
    return false;
  }
}

export function clearDraft() {
  try { localStorage.removeItem(KEY); } catch { /* ignore */ }
}

/** Human-readable age, e.g. "just now", "4 minutes ago". */
export function describeAge(iso) {
  const when = Date.parse(iso || '');
  if (!Number.isFinite(when)) return 'moments ago';
  const seconds = Math.max(0, Math.round((Date.now() - when) / 1000));
  if (seconds < 45) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

/**
 * Autosave `getProject()` on an interval and on page hide.
 * Returns a stop function. Safe to call when storage is unavailable.
 */
export function startAutosave(getProject, { intervalMs = INTERVAL_MS } = {}) {
  let last = '';
  const save = () => {
    const project = getProject();
    if (!project) return;
    let serialized;
    try {
      serialized = JSON.stringify(project);
    } catch {
      return;
    }
    if (serialized === last) return; // nothing changed since the last write
    if (writeDraft(project)) last = serialized;
  };
  const timer = setInterval(save, intervalMs);
  // pagehide/visibilitychange fire on tab close and mobile backgrounding,
  // where beforeunload is unreliable.
  const onHide = () => save();
  const onVisibility = () => { if (document.visibilityState === 'hidden') save(); };
  window.addEventListener('pagehide', onHide);
  document.addEventListener('visibilitychange', onVisibility);
  return () => {
    clearInterval(timer);
    window.removeEventListener('pagehide', onHide);
    document.removeEventListener('visibilitychange', onVisibility);
    save();
  };
}
