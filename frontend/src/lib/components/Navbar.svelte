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

<nav class="navbar bg-base-200" aria-label={$_('nav.mainNavigation')}>
	<div class="flex-1">
		<a href="/app" class="text-xl font-bold px-4">{$_('common.appName')}</a>
	</div>
	<div class="flex-none hidden md:flex items-center gap-2">
		<ul class="menu menu-horizontal px-1">
			{#each navLinks as link}
				<li>
					<a
						href={link.href}
						class={currentPath === link.href ? 'active' : ''}
						aria-current={currentPath === link.href ? 'page' : undefined}
					>
						{link.label}
					</a>
				</li>
			{/each}
		</ul>
		<button class="btn btn-ghost" onclick={onLogout}>{$_('auth.logOut')}</button>
	</div>
</nav>
