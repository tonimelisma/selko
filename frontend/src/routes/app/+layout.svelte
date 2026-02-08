<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { user, loading } from '$lib/stores.js';
	import { supabase } from '$lib/supabase.js';
	import Navbar from '$lib/components/Navbar.svelte';
	import BottomNav from '$lib/components/BottomNav.svelte';

	let { children } = $props();
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
	<title>Selko</title>
</svelte:head>

{#if isLoading}
	<div class="flex items-center justify-center min-h-screen">
		<span class="loading loading-spinner loading-lg"></span>
	</div>
{:else if currentUser}
	<div class="min-h-screen flex flex-col">
		<Navbar onLogout={handleLogout} />
		<main class="flex-1 pb-20 lg:pb-0">
			<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
				{@render children?.()}
			</div>
		</main>
		<BottomNav />
	</div>
{/if}
