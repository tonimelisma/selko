<script>
	import { page } from '$app/stores';
	import { _ } from 'svelte-i18n';

	let { onLogout } = $props();

	let currentPath = $state('/app');

	$effect(() => {
		const unsub = page.subscribe((p) => {
			currentPath = p.url.pathname;
		});
		return unsub;
	});

	let navLinks = $derived([
		{ href: '/app', label: $_('nav.review') },
		{ href: '/app/history', label: $_('nav.history') },
		{ href: '/app/settings', label: $_('nav.settings') }
	]);
</script>

<nav
	class="navbar sticky top-0 z-50 bg-base-200 min-h-12 px-1 sm:px-2"
	aria-label={$_('nav.mainNavigation')}
>
	<div class="flex-none">
		<a href="/app" class="btn btn-ghost btn-sm text-lg font-bold px-2 sm:px-3">
			{$_('common.appName')}
		</a>
	</div>
	<div class="flex-1"></div>
	<div class="flex-none flex items-center gap-0.5 sm:gap-2">
		<ul class="menu menu-horizontal menu-sm p-0 gap-0">
			{#each navLinks as link}
				<li>
					<a
						href={link.href}
						class="px-2 sm:px-3 {currentPath === link.href ? 'active' : ''}"
						aria-current={currentPath === link.href ? 'page' : undefined}
					>
						{link.label}
					</a>
				</li>
			{/each}
		</ul>
		<button class="btn btn-ghost btn-sm px-2 sm:px-3" onclick={onLogout}>
			{$_('auth.logOut')}
		</button>
	</div>
</nav>
