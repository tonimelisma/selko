<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { user, loading } from '$lib/stores.js';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';

	let isLoading = $state(true);
	/** @type {import('@supabase/supabase-js').User | null} */
	let currentUser = $state(null);

	onMount(() => {
		const unsubLoading = loading.subscribe((v) => {
			isLoading = v;
		});
		const unsubUser = user.subscribe((u) => {
			currentUser = u;
		});
		return () => {
			unsubLoading();
			unsubUser();
		};
	});

	$effect(() => {
		if (!isLoading) {
			if (currentUser) {
				goto('/app');
			} else {
				goto('/login');
			}
		}
	});
</script>

<div class="flex items-center justify-center min-h-screen">
	<LoadingSpinner />
</div>
