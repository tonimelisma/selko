/** @type {import('tailwindcss').Config} */
export default {
	content: ['./src/**/*.{html,js,svelte,ts}'],
	theme: {
		extend: {}
	},
	plugins: [require('daisyui')],
	daisyui: {
		themes: [
			{
				'selko-light': {
					'primary': '#5B63D3',
					'primary-content': '#FFFFFF',
					'secondary': '#6E7489',
					'secondary-content': '#FFFFFF',
					'accent': '#5B63D3',
					'accent-content': '#FFFFFF',
					'neutral': '#6E7489',
					'neutral-content': '#FFFFFF',
					'base-100': '#FFFFFF',
					'base-200': '#F1F2F6',
					'base-300': '#E2E4EB',
					'base-content': '#1A1C23',
					'info': '#5B63D3',
					'info-content': '#FFFFFF',
					'success': '#2D8659',
					'success-content': '#FFFFFF',
					'warning': '#B8860B',
					'warning-content': '#FFFFFF',
					'error': '#C4384B',
					'error-content': '#FFFFFF',
					'--rounded-box': '2px',
					'--rounded-btn': '2px',
					'--rounded-badge': '2px',
					'--tab-radius': '0px',
				}
			},
			{
				'selko-dark': {
					'primary': '#8B91D6',
					'primary-content': '#FFFFFF',
					'secondary': '#9BA0B3',
					'secondary-content': '#1A1C23',
					'accent': '#8B91D6',
					'accent-content': '#FFFFFF',
					'neutral': '#9BA0B3',
					'neutral-content': '#1A1C23',
					'base-100': '#1A1C23',
					'base-200': '#24272F',
					'base-300': '#353845',
					'base-content': '#E2E4EB',
					'info': '#8B91D6',
					'info-content': '#FFFFFF',
					'success': '#3DA873',
					'success-content': '#FFFFFF',
					'warning': '#D4A017',
					'warning-content': '#1A1C23',
					'error': '#E05566',
					'error-content': '#FFFFFF',
					'--rounded-box': '2px',
					'--rounded-btn': '2px',
					'--rounded-badge': '2px',
					'--tab-radius': '0px',
				}
			}
		],
		darkTheme: 'selko-dark'
	}
};
