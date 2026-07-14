<script>
	/** @type {{ size?: number, variant?: 'light' | 'dark' | 'onBrand' }} */
	let { size = 32, variant = 'light' } = $props();

	let blockColor = $derived(variant === 'dark' ? 'var(--color-logo-block)' : 'var(--color-base-100)');
</script>

<svg
	aria-hidden="true"
	width={size}
	height={size}
	viewBox="0 0 40 40"
	fill="none"
	class="shrink-0"
	style={`--logo-block: ${blockColor}`}
>
	<rect width="40" height="40" rx="12" fill="var(--color-primary)" />
	<rect x="9" y="10" width="9" height="9" rx="2.5" fill="var(--logo-block)" />
	<rect x="22" y="10" width="9" height="9" rx="2.5" fill="var(--logo-block)" opacity="0.55" />
	<rect x="9" y="23" width="22" height="8" rx="2.5" fill="var(--logo-block)" opacity="0.85" />
</svg>
