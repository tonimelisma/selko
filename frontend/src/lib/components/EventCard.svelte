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

<div class="card bg-base-100 shadow-sm border border-base-300 mb-3 max-w-3xl">
	<div class="card-body p-4">
		<!-- Content block -->
		<div>
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
						aria-expanded={showFullDescription}
					>
						{showFullDescription ? 'Less' : 'More'}
					</button>
				{/if}
			{/if}
		</div>
		<!-- Buttons row at bottom-right -->
		<div class="flex items-center justify-end gap-1 mt-3">
			<button class="btn btn-sm btn-primary" onclick={() => onapprove?.(event)} aria-label="Approve event">
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
				<span class="hidden lg:inline">Approve</span>
			</button>
			<button class="btn btn-sm btn-ghost" onclick={() => onedit?.(event)} aria-label="Edit event">
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
				<span class="hidden lg:inline">Edit</span>
			</button>
			<button class="btn btn-sm btn-ghost" onclick={() => onreject?.(event)} aria-label="Reject event">
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
				<span class="hidden lg:inline">Reject</span>
			</button>
		</div>
	</div>
</div>
