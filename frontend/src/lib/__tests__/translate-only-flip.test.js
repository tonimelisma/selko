// @ts-nocheck
import { describe, expect, it, vi } from 'vitest';
import { translateOnlyFlip } from '../translate-only-flip.js';

describe('translateOnlyFlip', () => {
	it('does not animate a card whose position did not change', () => {
		const rect = { left: 10, top: 20 };
		const animation = translateOnlyFlip(document.createElement('div'), {
			from: rect,
			to: rect
		});

		expect(animation.duration).toBe(0);
		expect(animation.css).toBeUndefined();
	});

	it('translates moving cards without scaling their contents', () => {
		window.matchMedia = vi.fn().mockReturnValue({ matches: false });
		const animation = translateOnlyFlip(
			document.createElement('div'),
			{
				from: { left: 10, top: 80 },
				to: { left: 10, top: 20 }
			},
			{ duration: 180 }
		);

		expect(animation.duration).toBe(180);
		expect(animation.css?.(0.5, 0.5)).toContain('translate3d(0px, 30px, 0)');
		expect(animation.css?.(0.5, 0.5)).not.toContain('scale');
	});
});
