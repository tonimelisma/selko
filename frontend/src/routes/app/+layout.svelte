<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { _ } from 'svelte-i18n';
	import { user, loading } from '$lib/stores.js';
	import { supabase } from '$lib/supabase.js';
	import Navbar from '$lib/components/Navbar.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import * as liveUpdates from '$lib/live-updates.js';

	let { children } = $props();
	/** @type {any} */
	let currentUser = $state(null);
	let isLoading = $state(true);

	onMount(() => {
		let currentUid = null;
		const unsubLoading = loading.subscribe((v) => {
			isLoading = v;
		});
		const unsubUser = user.subscribe((u) => {
			currentUser = u;
			if (!isLoading && !u) goto('/login');
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

		// Lifecycle catch-up: visible tab / online / focus
		// start() returns early when the channel already exists, so these
		// handlers call catchUp() — a synthetic invalidation for every
		// subscribed resource — which is what actually refetches.
		function onVisible() {
			if (document.visibilityState === 'visible' && currentUid) {
				liveUpdates.catchUp();
			}
		}
		function onOnline() {
			if (currentUid) liveUpdates.catchUp();
		}
		document.addEventListener('visibilitychange', onVisible);
		window.addEventListener('focus', onVisible);
		window.addEventListener('online', onOnline);

		return () => {
			unsubLoading();
			unsubUser();
			document.removeEventListener('visibilitychange', onVisible);
			window.removeEventListener('focus', onVisible);
			window.removeEventListener('online', onOnline);
			liveUpdates.stop();
		};
	});

	async function handleLogout() {
		await liveUpdates.stop();
		await supabase.auth.signOut();
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
{/if}
