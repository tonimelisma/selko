<script>
	import { _ } from 'svelte-i18n';

	let { title, subtitle = '', backHref = '', children = undefined } = $props();
</script>

<div class="mb-7 flex items-end justify-between gap-4">
	<div class="flex items-start gap-3">
		{#if backHref}
			<a href={backHref} class="btn btn-square btn-ghost btn-sm mt-1" aria-label={$_('common.goBack')}>
				<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
				</svg>
			</a>
		{/if}
		<div>
			<h1 class="text-3xl font-extrabold tracking-tight">{title}</h1>
			{#if subtitle}<p class="mt-1 text-sm text-base-content/60">{subtitle}</p>{/if}
		</div>
	</div>
	{#if children}
		<div class="hidden items-center gap-2 sm:flex">
			{@render children()}
		</div>
	{/if}
</div>
