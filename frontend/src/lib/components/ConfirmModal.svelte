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
		<div class="modal-action peer-action-wrap">
			<div class="peer-action-group peer-action-group--trailing" data-peer-count="2">
				<button class="btn peer-action peer-action-secondary" onclick={oncancel}>{$_('common.cancel')}</button>
				<button class="btn {confirmClass} peer-action" onclick={onconfirm}>{confirmText}</button>
			</div>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button>{$_('common.close')}</button>
	</form>
</dialog>
