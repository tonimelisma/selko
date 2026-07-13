<script>
	import { _ } from 'svelte-i18n';
	import { formatEventDateTime } from '$lib/format-event-datetime.js';

	let { event, isProcessing = false, onapprove, onreject } = $props();

	let sourceOrigin = $derived(() => {
		const sources = event.event_sources || [];
		return sources[0]?.source_origin || 'email';
	});

	let formattedDateTime = $derived(() => formatEventDateTime(event, $_));
</script>

<div class="flex items-start justify-between p-4 border-b border-base-200">
	<div class="min-w-0 flex-1">
		<div class="flex items-center gap-2">
			{#if sourceOrigin() === 'google_photos'}
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-base-content/50 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-label={$_('eventSource.photoSource')}>
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
				</svg>
			{:else}
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-base-content/50 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-label={$_('eventSource.emailSource')}>
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
				</svg>
			{/if}
			<a href="/app/events/{event.id}" class="link link-hover">
				<h4 class="font-semibold text-base">{event.title}</h4>
			</a>
			{#if event.importance === 'fyi'}
				<span class="badge badge-sm badge-info">{$_('events.fyi')}</span>
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
			<button class="btn btn-sm btn-success" disabled={isProcessing} onclick={() => onapprove?.(event)} aria-label={$_('events.acceptEvent')} aria-busy={isProcessing}>
				{#if isProcessing}
					<span class="loading loading-spinner loading-xs"></span>
				{:else}
					<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
				{/if}
			</button>
			<!-- Edit: filled primary button with icon + text -->
			<a href="/app/events/{event.id}" class="btn btn-sm btn-primary" aria-label={$_('common.edit')} class:btn-disabled={isProcessing}>
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
				{$_('common.edit')}
			</a>
			<!-- Reject: icon-only filled red button -->
			<button class="btn btn-sm btn-error" disabled={isProcessing} onclick={() => onreject?.(event)} aria-label={$_('events.rejectEvent')} aria-busy={isProcessing}>
				{#if isProcessing}
					<span class="loading loading-spinner loading-xs"></span>
				{:else}
					<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
				{/if}
			</button>
		</div>
	</div>
</div>
