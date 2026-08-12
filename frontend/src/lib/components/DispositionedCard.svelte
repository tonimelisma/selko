<script>
	import { fade, slide } from 'svelte/transition';

	/**
	 * Wraps EventCard/ChangeCard with disposition feedback.
	 * Implements review-queue-integrity.md §5.3.
	 * - Accept: success wash, check icon, "Accepted"
	 * - Reject: destructive wash, X icon, "Rejected", subtle offset
	 * Parent owns animate:flip (must be direct child of keyed each).
	 * This component handles only add/remove transitions and reduced-motion.
	 */
	let {
		event,
		kind = null, // 'accept' | 'reject' | null
		children,
		duration = 200
	} = $props();

	let reducedMotion = $state(false);
	if (typeof window !== 'undefined' && window.matchMedia) {
		const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
		reducedMotion = mq.matches;
		mq.addEventListener?.('change', (e) => (reducedMotion = e.matches));
	}
	let effectiveDuration = $derived(reducedMotion ? 0 : duration);
</script>

{#if kind === null}
	<div
		class="disposition-card"
		in:fade={{ duration: 0 }}
		out:slide={{ duration: effectiveDuration }}
		tabindex="-1"
		data-event-id={event.id}
	>
		{@render children?.()}
	</div>
{:else if kind === 'accept'}
	<div
		class="disposition-card disposition-accept bg-success/10 border-success/20 border rounded-xl p-1"
		in:fade={{ duration: 0 }}
		out:slide={{ duration: effectiveDuration }}
		tabindex="-1"
		data-event-id={event.id}
		role="status"
		aria-label="Accepted"
	>
		<div class="flex items-center gap-2 px-3 py-2 text-success">
			<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m5 12 4 4L19 6" /></svg>
			<span class="text-sm font-semibold">Accepted</span>
		</div>
		{@render children?.()}
	</div>
{:else}
	<div
		class="disposition-card disposition-reject bg-error/10 border-error/20 border rounded-xl p-1 translate-x-1"
		in:fade={{ duration: 0 }}
		out:slide={{ duration: effectiveDuration }}
		tabindex="-1"
		data-event-id={event.id}
		role="status"
		aria-label="Rejected"
	>
		<div class="flex items-center gap-2 px-3 py-2 text-error">
			<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
			<span class="text-sm font-semibold">Rejected</span>
		</div>
		{@render children?.()}
	</div>
{/if}
