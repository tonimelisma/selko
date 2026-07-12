/**
 * Recover from Safari/WebKit module load failures after the app has started.
 *
 * Initial entry-module failures are handled in app.html (before this file loads).
 * Vite emits `vite:preloadError` for later dynamic-import failures; without
 * handling, SvelteKit surfaces a blank "500 | Internal Error" page.
 */
const RELOAD_KEY = 'selko-js-mime-reload';
let reloading = false;

function reloadOnce() {
	if (reloading) return;
	reloading = true;
	try {
		if (sessionStorage.getItem(RELOAD_KEY)) return;
		sessionStorage.setItem(RELOAD_KEY, '1');
	} catch {
		/* ignore */
	}
	window.location.reload();
}

if (typeof window !== 'undefined') {
	// Successful boot — allow a future one-shot recovery if chunks go stale.
	try {
		sessionStorage.removeItem(RELOAD_KEY);
	} catch {
		/* ignore */
	}

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
