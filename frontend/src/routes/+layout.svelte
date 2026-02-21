<script>
	import '../app.css';
	import '$lib/i18n';
	import { onMount } from 'svelte';
	import { _, isLoading as isLocaleLoading } from 'svelte-i18n';
	import { initAuth } from '$lib/stores.js';

	let { children } = $props();

	onMount(() => {
		initAuth();
	});
</script>

{#if $isLocaleLoading}
	<div class="min-h-screen bg-base-100"></div>
{:else}
	<a href="#main-content" class="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:p-4 focus:bg-base-100 focus:text-base-content">{$_('common.skipToContent')}</a>
	<div class="min-h-screen bg-base-100">
		{@render children()}
	</div>
{/if}
