<script>
	let { heading, description } = $props();
</script>

<div class="warm-card flex flex-col items-center justify-center px-4 py-16 text-center">
	<div class="mb-5 grid h-[60px] w-[60px] place-items-center rounded-[20px] bg-base-200 text-success">
		<svg xmlns="http://www.w3.org/2000/svg" class="h-7 w-7" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
			<path stroke-linecap="round" stroke-linejoin="round" d="m5 12 4 4L19 6" />
		</svg>
	</div>
	<h3 class="mb-2 text-lg font-extrabold">{heading}</h3>
	<p class="max-w-md text-sm text-base-content/60">{description}</p>
</div>
