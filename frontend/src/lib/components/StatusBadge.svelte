<script>
	import StatusIndicator from './StatusIndicator.svelte';
	/** @type {{ status: string, type?: 'event' | 'integration', label?: string }} */
	let { status, type = 'event', label = undefined } = $props();
</script>

<StatusIndicator {status} {type} {label} />
