<script>
	/** @type {{ size?: 'xs' | 'sm' | 'md' | 'lg', class?: string }} */
	let { size = 'lg', class: className = '' } = $props();

	const sizeClass = {
		xs: 'loading-xs',
		sm: 'loading-sm',
		md: 'loading-md',
		lg: 'loading-lg'
	};
</script>

<div class="flex justify-center items-center py-8 {className}">
	<span class="loading loading-spinner {sizeClass[size]}" aria-hidden="true"></span>
	<span class="sr-only">Loading...</span>
</div>
