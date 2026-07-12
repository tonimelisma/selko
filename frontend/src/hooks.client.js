/**
 * One-shot recovery from Safari/WebKit module load failures.
 *
 * Infinite-loop bug (fixed): clearing the sessionStorage guard as soon as
 * hooks.client.js loaded meant every reload reset the guard, so a sticky
 * vite:preloadError (stale cached chunks after deploy) reloaded forever.
 *
 * Allow at most one automatic reload while the guard is set. After the app
 * stays up for CLEAR_AFTER_MS, clear the guard so a later deploy can recover.
 */
const RELOAD_KEY = 'selko-js-mime-reload';
const CLEAR_AFTER_MS = 30_000;
let reloading = false;

function alreadyRecovered() {
	try {
		return Boolean(sessionStorage.getItem(RELOAD_KEY));
	} catch {
		return false;
	}
}

function markRecovered() {
	try {
		sessionStorage.setItem(RELOAD_KEY, '1');
	} catch {
		/* ignore */
	}
}

function clearRecovered() {
	try {
		sessionStorage.removeItem(RELOAD_KEY);
	} catch {
		/* ignore */
	}
}

function reloadOnce() {
	if (reloading || alreadyRecovered()) return;
	reloading = true;
	markRecovered();
	window.location.reload();
}

if (typeof window !== 'undefined') {
	// After a recovery reload (or a healthy first boot), clear the guard once
	// the app has stayed up — so a future deploy can still one-shot recover.
	window.setTimeout(clearRecovered, CLEAR_AFTER_MS);

	window.addEventListener('vite:preloadError', (event) => {
		event.preventDefault();
		reloadOnce();
	});

	window.addEventListener('unhandledrejection', (event) => {
		const msg = String(event.reason?.message || event.reason || '');
		if (!msg.includes('MIME type')) return;
		event.preventDefault();
		reloadOnce();
	});
}
