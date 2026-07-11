<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { _ } from 'svelte-i18n';
	import { user, loading } from '$lib/stores.js';
	import { supabase } from '$lib/supabase.js';
	import Navbar from '$lib/components/Navbar.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';

	let { children } = $props();
	/** @type {any} */
	let currentUser = $state(null);
	let isLoading = $state(true);

	onMount(() => {
		const unsubLoading = loading.subscribe((v) => {
			isLoading = v;
		});
		const unsubUser = user.subscribe((u) => {
			currentUser = u;
			if (!isLoading && !u) goto('/login');
		});
		return () => {
			unsubLoading();
			unsubUser();
		};
	});

	async function handleLogout() {
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
	<div class="min-h-screen flex flex-col overflow-x-hidden">
		<Navbar onLogout={handleLogout} />
		<main id="main-content" class="flex-1">
			<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
				{@render children?.()}
			</div>
		</main>
	</div>
{/if}
