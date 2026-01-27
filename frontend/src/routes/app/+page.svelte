<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { supabase } from '$lib/supabase.js';
	import { user, loading } from '$lib/stores.js';

	/** @type {import('@supabase/supabase-js').User | null} */
	let currentUser = $state(null);
	let isLoading = $state(true);

	onMount(() => {
		const unsubLoading = loading.subscribe((loadingState) => {
			isLoading = loadingState;
		});

		const unsubUser = user.subscribe((u) => {
			currentUser = u;
			if (!isLoading && !u) {
				goto('/login');
			}
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
	<div class="min-h-screen">
		<div class="navbar bg-base-200">
			<div class="flex-1">
				<span class="text-xl font-bold px-4">Selko</span>
			</div>
			<div class="flex-none">
				<button class="btn btn-ghost" onclick={handleLogout}>Logout</button>
			</div>
		</div>

		<div class="flex items-center justify-center" style="min-height: calc(100vh - 64px);">
			<div class="text-center">
				<h1 class="text-4xl font-bold mb-4">Hello, {currentUser.email}!</h1>
				<p class="text-base-content/70">Welcome to Selko</p>
			</div>
		</div>
	</div>
{/if}
