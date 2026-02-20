<script>
	let {
		sender,
		senderEmail = '',
		eventCount = 0,
		onapproveAll,
		onrejectAll,
		onignoreSender,
		onautoApproveSender
	} = $props();
</script>

<div class="flex items-center justify-between py-3 px-1">
	<div>
		<h2 class="font-semibold text-base-content">{sender}</h2>
		<p class="text-sm text-base-content/60">
			{eventCount} {eventCount === 1 ? 'event' : 'events'}
		</p>
	</div>
	<div class="dropdown dropdown-end">
		<div tabindex="0" role="button" class="btn btn-ghost btn-sm btn-square" aria-label="Actions for {sender}">
			<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v.01M12 12v.01M12 19v.01" /></svg>
		</div>
		<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
		<ul tabindex="0" class="dropdown-content z-[1] menu p-2 shadow bg-base-100 rounded-box w-52">
			{#if eventCount > 1}
				<li>
					<button onclick={() => { onapproveAll?.(); /** @type {HTMLElement} */ (document.activeElement)?.blur(); }}>
						<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
						Approve all
					</button>
				</li>
				<li>
					<button class="text-error" onclick={() => { onrejectAll?.(); /** @type {HTMLElement} */ (document.activeElement)?.blur(); }}>
						<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
						Reject all
					</button>
				</li>
				<div class="divider my-0"></div>
			{/if}
			<li>
				<button onclick={() => { onautoApproveSender?.(); /** @type {HTMLElement} */ (document.activeElement)?.blur(); }}>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
					Auto-approve sender
				</button>
			</li>
			<li>
				<button class="text-error" onclick={() => { onignoreSender?.(); /** @type {HTMLElement} */ (document.activeElement)?.blur(); }}>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" /></svg>
					Ignore sender
				</button>
			</li>
		</ul>
	</div>
</div>
