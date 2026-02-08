<script>
	let { title, backHref = '', children = undefined } = $props();
</script>

<div class="flex items-center justify-between mb-6">
	<div class="flex items-center gap-3">
		{#if backHref}
			<a href={backHref} class="btn btn-ghost btn-sm" aria-label="Go back">
				<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
				</svg>
			</a>
		{/if}
		<h1 class="text-2xl font-bold">{title}</h1>
	</div>
	{#if children}
		<div class="flex items-center gap-2">
			{@render children()}
		</div>
	{/if}
</div>
