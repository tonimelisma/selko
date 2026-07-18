<script>
	import { _ } from 'svelte-i18n';
	/** @type {{ status: string, type?: 'event' | 'integration' }} */
	let { status, type = 'event' } = $props();

	let info = $derived(() => {
		if (type === 'integration') {
			return status === 'active'
				? { tone: 'success', label: $_('status.connected'), icon: 'check' }
				: { tone: status === 'not_connected' ? 'neutral' : 'error', label: status === 'not_connected' ? $_('status.notConnected') : $_(`status.${status}`), icon: status === 'not_connected' ? 'circle' : 'error' };
		}
		/** @type {Record<string, [string, string, string]>} */
		const map = {
			pending_review: ['neutral', $_('status.pending'), 'circle'],
			approved: ['success', $_('status.approved'), 'check'],
			synced: ['success', $_('status.synced'), 'check'],
			sync_failed: ['error', $_('status.failed'), 'error'],
			rejected: ['error', $_('status.rejected'), 'x'],
			cancelled: ['neutral', $_('status.cancelled'), 'minus'],
			syncing: ['neutral', $_('status.syncing'), 'circle']
		};
		const value = map[status] || ['neutral', status, 'circle'];
		return { tone: value[0], label: value[1], icon: value[2] };
	});
</script>

<span class="status-indicator semantic-status-{info().tone}" role="status">
	<svg viewBox="0 0 20 20" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
		<circle cx="10" cy="10" r="7" />
		{#if info().icon === 'check'}<path d="m6.5 10 2.2 2.2 4.8-5" />
		{:else if info().icon === 'x'}<path d="m7 7 6 6m0-6-6 6" />
		{:else if info().icon === 'error'}<path d="M10 6.5v4.5m0 2.5v.1" />
		{:else if info().icon === 'minus'}<path d="M7 10h6" />{/if}
	</svg>
	<span>{info().label}</span>
</span>
