<script>
	import { _ } from 'svelte-i18n';

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

<dialog bind:this={dialogEl} class="modal" onclose={oncancel} aria-labelledby="modal-title" aria-describedby="modal-description">
	<div class="modal-box warm-card">
		<h3 id="modal-title" class="text-lg font-extrabold">{title}</h3>
		<p id="modal-description" class="py-4 text-sm text-base-content/70">{description}</p>
		<div class="modal-action">
			<button class="btn action-tertiary" onclick={oncancel}>{$_('common.cancel')}</button>
			<button class="btn {confirmClass}" onclick={onconfirm}>{confirmText}</button>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button>{$_('common.close')}</button>
	</form>
</dialog>
