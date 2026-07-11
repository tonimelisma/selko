<script>
	import { _ } from 'svelte-i18n';

	let { status, type = 'event' } = $props();

	let eventStatusMap = $derived(/** @type {Record<string, {class: string, label: string}>} */ ({
		pending_review: { class: 'badge-warning', label: $_('status.pending') },
		pending_change: { class: 'badge-warning', label: $_('status.pendingChange') },
		approved: { class: 'badge-info', label: $_('status.approved') },
		syncing: { class: 'badge-info', label: $_('status.syncing') },
		synced: { class: 'badge-success', label: $_('status.synced') },
		sync_failed: { class: 'badge-error', label: $_('status.failed') },
		rejected: { class: 'badge-ghost', label: $_('status.rejected') },
		cancelled: { class: 'badge-ghost', label: $_('status.cancelled') }
	}));

	let integrationStatusMap = $derived(/** @type {Record<string, {class: string, label: string}>} */ ({
		active: { class: 'badge-success', label: $_('status.authorized') },
		expired: { class: 'badge-error', label: $_('status.expired') },
		revoked: { class: 'badge-error', label: $_('status.revoked') },
		error: { class: 'badge-error', label: $_('status.error') },
		not_connected: { class: 'badge-ghost', label: $_('status.notConnected') }
	}));

	let badgeInfo = $derived(() => {
		/** @type {Record<string, {class: string, label: string}>} */
		const map = type === 'integration' ? integrationStatusMap : eventStatusMap;
		return map[status] || { class: 'badge-ghost', label: status };
	});
</script>

<span class="badge {badgeInfo().class}" role="status">{badgeInfo().label}</span>
