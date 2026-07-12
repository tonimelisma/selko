/**
 * Recover from Safari/WebKit module load failures.
 *
 * When a dynamic import fails (cancelled preload, stale chunk after deploy),
 * Vite emits `vite:preloadError`. Without handling, SvelteKit surfaces a
 * blank "500 | Internal Error" page even though the CDN is fine.
 */
let reloading = false;

if (typeof window !== 'undefined') {
	window.addEventListener('vite:preloadError', (event) => {
		event.preventDefault();
		if (reloading) return;
		reloading = true;
		window.location.reload();
	});
}
