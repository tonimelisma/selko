<script>
	import StatusIndicator from './StatusIndicator.svelte';
	/** @type {{ status: string, type?: 'event' | 'integration' }} */
	let { status, type = 'event' } = $props();
</script>

<StatusIndicator {status} {type} />
