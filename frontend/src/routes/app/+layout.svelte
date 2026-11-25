<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { _ } from 'svelte-i18n';
	import { user, loading, authUnavailable, retryAuth } from '$lib/stores.js';
	import { signOut } from '$lib/auth.js';
	import Navbar from '$lib/components/Navbar.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import * as liveUpdates from '$lib/live-updates.js';

	let { children } = $props();
	/** @type {any} */
	let currentUser = $state(null);
	let isLoading = $state(true);
	let isUnavailable = $state(false);

	/**
	 * Sign-in keeps the deep link the user opened (for example an event) and
	 * returns to it; login only honours same-origin paths.
	 */
	function loginPath() {
		const here = window.location.pathname + window.location.search;
		if (here === '/app' || !here.startsWith('/app')) return '/login';
		return `/login?next=${encodeURIComponent(here)}`;
	}

	onMount(() => {
		/** @type {string | null} */
		let currentUid = null;
		const unsubLoading = loading.subscribe((v) => {
			isLoading = v;
		});
		const unsubUnavailable = authUnavailable.subscribe((v) => {
			isUnavailable = v;
		});
		const unsubUser = user.subscribe((u) => {
			currentUser = u;
			const uid = u?.id || null;
			if (uid !== currentUid) {
				currentUid = uid;
				if (uid) {
					liveUpdates.start(uid);
				} else {
					liveUpdates.stop();
				}
			}
		});

		// Lifecycle catch-up: visible tab / online / focus. start() is a
		// no-op while the stream is open, so these call catchUp() — a synthetic
		// invalidation for every subscribed resource — which refetches.
		function onVisible() {
			if (document.visibilityState === 'visible' && currentUid) {
				liveUpdates.catchUp();
			}
		}
		function onOnline() {
			if (currentUid) liveUpdates.catchUp();
			else if (isUnavailable) retryAuth();
		}
		document.addEventListener('visibilitychange', onVisible);
		window.addEventListener('focus', onVisible);
		window.addEventListener('online', onOnline);

		return () => {
			unsubLoading();
			unsubUnavailable();
			unsubUser();
			document.removeEventListener('visibilitychange', onVisible);
			window.removeEventListener('focus', onVisible);
			window.removeEventListener('online', onOnline);
			liveUpdates.stop();
		};
	});

	// Signed out (or never signed in): to the login page. Not while Selko is
	// unreachable — a signed-in user gets a retry instead of the login page.
	$effect(() => {
		if (!isLoading && !currentUser && !isUnavailable) goto(loginPath());
	});

	async function handleLogout() {
		await liveUpdates.stop();
		await signOut();
		goto('/login');
	}
</script>

<svelte:head>
	<title>{$_('common.appName')}</title>
</svelte:head>

{#if isLoading}
	<div class="min-h-screen" aria-busy="true">
		<LoadingSpinner class="min-h-screen" />
	</div>
{:else if currentUser}
	<div class="min-h-screen overflow-x-hidden">
		<Navbar onLogout={handleLogout} />
		<main id="main-content" class="min-h-screen lg:ml-[236px]">
			<div class="mx-auto max-w-[1120px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
				{@render children?.()}
			</div>
		</main>
	</div>
{:else if isUnavailable}
	<main id="main-content" class="flex min-h-screen items-center justify-center px-4">
		<div class="warm-card w-full max-w-sm">
			<div class="card-body items-center text-center" role="alert" aria-live="polite">
				<h1 class="text-xl font-bold">{$_('auth.cantReach')}</h1>
				<p class="text-sm text-base-content/70">{$_('auth.cantReachDescription')}</p>
				<button class="btn btn-primary mt-4 min-h-11 rounded-[14px]" onclick={() => retryAuth()}>
					{$_('common.retry')}
				</button>
			</div>
		</div>
	</main>
{/if}
