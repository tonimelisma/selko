<script>
	let {
		open = false,
		title = 'Confirm',
		description = '',
		confirmText = 'Confirm',
		confirmClass = 'btn-error',
		onconfirm,
		oncancel
	} = $props();

	/** @type {HTMLDialogElement | null} */
	let dialogEl = $state(null);

	$effect(() => {
		if (dialogEl) {
			if (open) {
				dialogEl.showModal?.();
			} else {
				dialogEl.close?.();
			}
		}
	});
</script>

<dialog bind:this={dialogEl} class="modal" onclose={oncancel}>
	<div class="modal-box">
		<h3 class="font-bold text-lg">{title}</h3>
		<p class="py-4">{description}</p>
		<div class="modal-action">
			<button class="btn" onclick={oncancel}>Cancel</button>
			<button class="btn {confirmClass}" onclick={onconfirm}>{confirmText}</button>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button>close</button>
	</form>
</dialog>
