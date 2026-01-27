<script>
	import '../app.css';
	import { onMount } from 'svelte';
	import { initAuth } from '$lib/stores.js';

	let { children } = $props();

	onMount(() => {
		initAuth();
	});
</script>

<div class="min-h-screen bg-base-100">
	{@render children()}
</div>
