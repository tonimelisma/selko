<script>
	let { kind = 'new', label = '' } = $props();
</script>

<span class="state-tag {kind === 'changed' ? 'badge-changed' : 'badge-new'}">{label}</span>
