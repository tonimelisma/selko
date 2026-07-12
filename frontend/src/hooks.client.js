/**
 * Recover from Vite dynamic-import failures (stale chunks after deploy).
 *
 * Critical: only call preventDefault() when we actually reload. Otherwise
 * Safari ends on a blank white SPA shell with the error swallowed.
 *
 * Throttle: at most one reload per 10s (n8n/Vite community pattern).
 */
const RELOAD_TS_KEY = 'selko-vite-preload-reload-ts';
const RELOAD_THROTTLE_MS = 10_000;

/** @param {Event} event */
function reloadOnce(event) {
	const now = Date.now();
	try {
		const last = Number(sessionStorage.getItem(RELOAD_TS_KEY) || 0);
		if (now - last < RELOAD_THROTTLE_MS) {
			// Recently reloaded already — do NOT preventDefault; let the error show.
			return false;
		}
		sessionStorage.setItem(RELOAD_TS_KEY, String(now));
	} catch {
		// sessionStorage unavailable — still attempt a single reload this load.
	}

	event.preventDefault();
	window.location.reload();
	return true;
}

if (typeof window !== 'undefined') {
	window.addEventListener('vite:preloadError', (event) => {
		reloadOnce(event);
	});

	window.addEventListener('unhandledrejection', (event) => {
		const msg = String(event.reason?.message || event.reason || '');
		if (!msg.includes('MIME type') && !msg.includes('Failed to fetch dynamically imported module')) {
			return;
		}
		reloadOnce(event);
	});
}
