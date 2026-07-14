<script>
	import { _ } from 'svelte-i18n';
	import { initialsFromEmail, senderAvatarTone } from '$lib/user-display.js';

	let {
		sender,
		senderEmail = '',
		eventCount = 0,
		isPhotoSource = false,
		onapproveAll,
		onrejectAll,
		onignoreSender,
		onautoApproveSender
	} = $props();

	let hasDropdownItems = $derived(eventCount > 1 || !isPhotoSource);
	let tone = $derived(senderAvatarTone(senderEmail || sender));
	let avatarInitials = $derived(initialsFromEmail(senderEmail || sender));
	let menuOpen = $state(false);

	/** @param {(() => void) | undefined} action */
	function runAndClose(action) {
		menuOpen = false;
		action?.();
	}
</script>

<div class="flex items-start justify-between gap-3 p-4">
	<div class="flex min-w-0 items-center gap-3">
		<div
			class="grid h-11 w-11 shrink-0 place-items-center rounded-[13px] text-sm font-bold text-primary-content"
			class:bg-primary={tone === 'primary'}
			class:bg-accent={tone === 'accent'}
			class:bg-success={tone === 'success'}
		>
			{avatarInitials}
		</div>
		<div class="min-w-0">
			<h2 class="truncate text-[15px] font-bold">{sender}</h2>
			<p class="text-xs text-base-content/55">
				{$_('events.eventCount', { values: { count: eventCount } })}
			</p>
		</div>
	</div>
	{#if hasDropdownItems}
		<button class="btn btn-square btn-sm rounded-[11px] bg-base-200 text-base-content" aria-label={$_('senderActions.actionsFor', { values: { sender } })} aria-expanded={menuOpen} onclick={() => (menuOpen = !menuOpen)}>
			<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 transition-transform {menuOpen ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m6 9 6 6 6-6" /></svg>
		</button>
	{/if}
</div>

{#if hasDropdownItems && menuOpen}
	<div class="mx-4 mb-4 rounded-[15px] border border-secondary/20 bg-base-100 p-2 shadow-popover">
		{#if eventCount > 1}
			<div class="flex items-center justify-between gap-3 px-2 py-2">
				<span class="text-xs font-semibold text-base-content/65">{$_('senderActions.bulkActions')}</span>
				<div class="flex gap-1">
					<button class="btn btn-ghost btn-xs" onclick={() => runAndClose(onapproveAll)}>{$_('senderActions.approveAll')}</button>
					<button class="btn btn-ghost btn-xs text-error" onclick={() => runAndClose(onrejectAll)}>{$_('senderActions.rejectAll')}</button>
				</div>
			</div>
			<div class="my-1 border-t border-base-300"></div>
		{/if}
		{#if !isPhotoSource}
			<button class="w-full rounded-lg px-2 py-2 text-left text-sm font-semibold hover:bg-base-200" onclick={() => runAndClose(onautoApproveSender)}>{$_('senderActions.autoApproveSender')}</button>
			<div class="my-1 border-t border-base-300"></div>
			<button class="w-full rounded-lg px-2 py-2 text-left text-sm font-semibold text-error hover:bg-base-200" onclick={() => runAndClose(onignoreSender)}>{$_('senderActions.ignoreSender')}</button>
		{/if}
	</div>
{/if}
