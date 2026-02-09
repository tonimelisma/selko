<script>
	let { sender, eventCount = 0, onapproveAll } = $props();
</script>

<div class="flex items-center justify-between py-3 px-1">
	<div>
		<h2 class="font-semibold text-base-content">{sender}</h2>
		<p class="text-sm text-base-content/60">
			{eventCount} {eventCount === 1 ? 'event' : 'events'}
		</p>
	</div>
	{#if eventCount > 1}
		<button class="btn btn-ghost btn-sm" onclick={onapproveAll} aria-label="Approve all events from {sender}">Approve All</button>
	{/if}
</div>
