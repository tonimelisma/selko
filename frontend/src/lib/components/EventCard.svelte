<script>
	let { event, onapprove, onreject, onedit = undefined } = $props();

	let showFullDescription = $state(false);

	let formattedDateTime = $derived(() => {
		if (event.all_day) return 'All Day';
		if (!event.start_datetime) return '';
		try {
			const start = new Date(event.start_datetime);
			const dateStr = start.toLocaleDateString(undefined, {
				weekday: 'short',
				month: 'short',
				day: 'numeric'
			});
			const timeStr = start.toLocaleTimeString(undefined, {
				hour: 'numeric',
				minute: '2-digit'
			});
			let result = `${dateStr}, ${timeStr}`;
			if (event.end_datetime) {
				const end = new Date(event.end_datetime);
				const endTimeStr = end.toLocaleTimeString(undefined, {
					hour: 'numeric',
					minute: '2-digit'
				});
				result += ` - ${endTimeStr}`;
			}
			return result;
		} catch {
			return event.start_datetime;
		}
	});

	let truncatedDescription = $derived(() => {
		if (!event.description) return '';
		if (showFullDescription || event.description.length <= 120) return event.description;
		return event.description.slice(0, 120) + '...';
	});

	let showToggle = $derived(event.description && event.description.length > 120);
</script>

<div class="card bg-base-100 shadow-sm border border-base-300 mb-3">
	<div class="card-body p-4">
		<div class="flex items-start justify-between gap-2">
			<div class="min-w-0 flex-1">
				<a href="/app/events/{event.id}" class="link link-hover" onclick={(e) => { if (onedit) { e.preventDefault(); onedit(event); } }}>
					<h4 class="font-semibold text-base">{event.title}</h4>
				</a>
				<p class="text-sm text-base-content/70 mt-1">{formattedDateTime()}</p>
				{#if event.location}
					<p class="text-sm text-base-content/60 mt-0.5">{event.location}</p>
				{/if}
				{#if event.description}
					<p class="text-sm text-base-content/50 mt-2">{truncatedDescription()}</p>
					{#if showToggle}
						<button
							class="btn btn-ghost btn-xs mt-1 px-0"
							onclick={() => (showFullDescription = !showFullDescription)}
						>
							{showFullDescription ? 'Less' : 'More'}
						</button>
					{/if}
				{/if}
			</div>
			<div class="flex items-center gap-1 flex-shrink-0">
				<button
					class="btn btn-sm btn-ghost"
					onclick={() => onreject?.(event)}
					aria-label="Reject event"
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
					<span class="hidden lg:inline">Reject</span>
				</button>
				<button
					class="btn btn-sm btn-primary"
					onclick={() => onapprove?.(event)}
					aria-label="Approve event"
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
					</svg>
					<span class="hidden lg:inline">Approve</span>
				</button>
			</div>
		</div>
	</div>
</div>
