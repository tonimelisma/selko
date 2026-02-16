<script>
	let { event, onapprove, onreject } = $props();

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
</script>

<div class="flex items-start justify-between p-4 border-b border-base-200">
	<div class="min-w-0 flex-1">
		<div class="flex items-center gap-2">
			<a href="/app/events/{event.id}" class="link link-hover">
				<h4 class="font-semibold text-base">{event.title}</h4>
			</a>
			{#if event.importance === 'fyi'}
				<span class="badge badge-sm badge-info">FYI</span>
			{/if}
		</div>
		<p class="text-sm text-base-content/70 mt-1">{formattedDateTime()}</p>
		{#if event.location}
			<p class="text-sm text-base-content/60 mt-0.5">{event.location}</p>
		{/if}
		{#if event.description}
			<p class="text-sm text-base-content/50 mt-1 line-clamp-2">{event.description}</p>
		{/if}
		<!-- Action buttons row -->
		<div class="flex items-center gap-2 mt-2">
			<!-- Accept: icon-only filled green button -->
			<button class="btn btn-sm btn-success" onclick={() => onapprove?.(event)} aria-label="Accept event">
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
			</button>
			<!-- Edit: filled primary button with icon + text -->
			<a href="/app/events/{event.id}" class="btn btn-sm btn-primary" aria-label="Edit event">
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
				Edit
			</a>
			<!-- Reject: icon-only filled red button -->
			<button class="btn btn-sm btn-error" onclick={() => onreject?.(event)} aria-label="Reject event">
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
			</button>
		</div>
	</div>
</div>
