<script>
	import { _ } from 'svelte-i18n';
	import { formatEventDateTime } from '$lib/format-event-datetime.js';
	import StateTag from './StateTag.svelte';

	let { event, isProcessing = false, onapprove, onreject } = $props();

	let sourceOrigin = $derived(() => {
		const sources = event.event_sources || [];
		return sources[0]?.source_origin || 'email';
	});

	let formattedDateTime = $derived(() => formatEventDateTime(event, $_));
	let dateParts = $derived(() => {
		if (!event.start_datetime) return { month: '', day: '' };
		const date = new Date(event.start_datetime);
		return {
			month: date.toLocaleDateString(undefined, { month: 'short' }).toUpperCase(),
			day: date.toLocaleDateString(undefined, { day: 'numeric' })
		};
	});
</script>

<div class="warm-card-row flex gap-3 border-b border-base-300 p-4 sm:gap-4">
	<div class="date-chip flex h-[52px] w-[50px] shrink-0 flex-col items-center justify-center">
		{#if dateParts().month}
			<span class="text-[10px] font-bold tracking-[0.12em] text-primary">{dateParts().month}</span>
			<span class="text-xl font-extrabold leading-5">{dateParts().day}</span>
		{:else}
			<span class="text-xs font-bold text-primary">—</span>
		{/if}
	</div>

	<div class="min-w-0 flex-1">
		<div class="flex flex-wrap items-center gap-2">
			{#if sourceOrigin() === 'google_photos'}
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 shrink-0 text-base-content/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-label={$_('eventSource.photoSource')}>
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
				</svg>
			{:else}
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 shrink-0 text-base-content/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-label={$_('eventSource.emailSource')}>
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5v10a2 2 0 002 2z" />
				</svg>
			{/if}
			<a href="/app/events/{event.id}" class="min-w-0 link link-hover">
				<h4 class="truncate text-[15px] font-bold">{event.title}</h4>
			</a>
			{#if event.importance === 'fyi'}
				<span class="badge badge-neutral-warm badge-sm">{$_('events.fyi')}</span>
			{:else}
				<StateTag kind="new" label={$_('home.newSection')} />
			{/if}
		</div>
		<p class="mt-1 text-[12px] font-medium text-base-content/55">{formattedDateTime()}</p>
		{#if event.location}
			<p class="mt-0.5 text-[13px] text-base-content/70">{event.location}</p>
		{/if}
		{#if event.description}
			<p class="mt-1 line-clamp-2 text-[13px] text-base-content/60">{event.description}</p>
		{/if}
		<div class="mt-3 flex items-center gap-2">
			<button class="btn btn-success flex-1" disabled={isProcessing} onclick={() => onapprove?.(event)} aria-label={$_('events.acceptEvent')} aria-busy={isProcessing}>
				{#if isProcessing}<span class="loading loading-spinner loading-xs"></span>{:else}<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="m5 12 4 4L19 6" /></svg>{/if}
				<span>{$_('events.accept')}</span>
			</button>
			<a href="/app/events/{event.id}" class="btn btn-square bg-base-200 text-base-content" class:btn-disabled={isProcessing} aria-label={$_('common.edit')}>
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="m15 5 4 4M4 20l4.5-1 10-10a2.1 2.1 0 0 0-3-3l-10 10L4 20z" /></svg>
			</a>
			<button class="btn btn-square bg-base-200 text-error" disabled={isProcessing} onclick={() => onreject?.(event)} aria-label={$_('events.rejectEvent')} aria-busy={isProcessing}>
				{#if isProcessing}<span class="loading loading-spinner loading-xs"></span>{:else}<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" d="m7 7 10 10M17 7 7 17" /></svg>{/if}
			</button>
		</div>
	</div>
</div>
