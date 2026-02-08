<script>
	let { status, type = 'event' } = $props();

	const eventStatusMap = {
		pending_review: { class: 'badge-warning', label: 'Pending' },
		approved: { class: 'badge-info', label: 'Approved' },
		syncing: { class: 'badge-info', label: 'Syncing' },
		synced: { class: 'badge-success', label: 'Synced' },
		sync_failed: { class: 'badge-error', label: 'Failed' },
		rejected: { class: 'badge-ghost', label: 'Rejected' },
		cancelled: { class: 'badge-ghost', label: 'Cancelled' }
	};

	const integrationStatusMap = {
		active: { class: 'badge-success', label: 'Authorized' },
		expired: { class: 'badge-error', label: 'Expired' },
		revoked: { class: 'badge-error', label: 'Revoked' },
		error: { class: 'badge-error', label: 'Error' },
		not_connected: { class: 'badge-ghost', label: 'Not Connected' }
	};

	let badgeInfo = $derived(() => {
		/** @type {Record<string, {class: string, label: string}>} */
		const map = type === 'integration' ? integrationStatusMap : eventStatusMap;
		return map[status] || { class: 'badge-ghost', label: status };
	});
</script>

<span class="badge {badgeInfo().class}">{badgeInfo().label}</span>
