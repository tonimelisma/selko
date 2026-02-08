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
		<h3 class="font-medium text-sm truncate">{subject || 'No subject'}</h3>
		{#if formattedDate()}
			<p class="text-xs text-base-content/50">{formattedDate()}</p>
		{/if}
	</div>
	{#if eventCount > 1}
		<button class="btn btn-ghost btn-xs ml-2" onclick={onapproveAll}>Approve All</button>
	{/if}
</div>
