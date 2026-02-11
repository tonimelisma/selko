<script>
	let { subject = '', date = '', eventCount = 0, onapproveAll } = $props();

	let formattedDate = $derived(() => {
		if (!date) return '';
		try {
			return new Date(date).toLocaleDateString(undefined, {
				month: 'short',
				day: 'numeric',
				year: 'numeric'
			});
		} catch {
			return date;
		}
	});
</script>

<div class="flex items-center justify-between py-2 px-1 border-b border-base-300">
	<div class="min-w-0 flex-1">
		<div class="flex items-center gap-1.5">
			<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5 text-base-content/40 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>
			<h3 class="font-medium text-sm truncate">{subject || 'No subject'}</h3>
		</div>
		{#if formattedDate()}
			<p class="text-xs text-base-content/50">{formattedDate()}</p>
		{/if}
	</div>
	{#if eventCount > 1}
		<button class="btn btn-ghost btn-xs ml-2" onclick={onapproveAll} aria-label="Approve all events from this email">Approve All</button>
	{/if}
</div>
