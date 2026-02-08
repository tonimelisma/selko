<script>
	let { heading, description } = $props();
</script>

<div class="flex flex-col items-center justify-center py-16 px-4 text-center">
	<h3 class="text-lg font-semibold mb-2">{heading}</h3>
	<p class="text-base-content/70 max-w-md">{description}</p>
</div>
