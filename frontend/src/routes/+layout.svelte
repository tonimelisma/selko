<script>
	import '../app.css';
	import { onMount } from 'svelte';
	import { initAuth } from '$lib/stores.js';

	let { children } = $props();

	onMount(() => {
		initAuth();
	});
</script>

<a href="#main-content" class="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:p-4 focus:bg-base-100 focus:text-base-content">Skip to content</a>
<div class="min-h-screen bg-base-100">
	{@render children()}
</div>
