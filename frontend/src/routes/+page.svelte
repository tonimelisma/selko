<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { user, loading } from '$lib/stores.js';

	onMount(() => {
		const unsubscribe = loading.subscribe((isLoading) => {
			if (!isLoading) {
				user.subscribe((currentUser) => {
					if (currentUser) {
						goto('/app');
					} else {
						goto('/login');
					}
				})();
			}
		});

		return unsubscribe;
	});
</script>

<div class="flex items-center justify-center min-h-screen">
	<span class="loading loading-spinner loading-lg"></span>
</div>
