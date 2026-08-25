// @ts-check
import { defineConfig } from 'astro/config';
import { unified } from '@astrojs/markdown-remark';
import starlight from '@astrojs/starlight';
import astroD2 from 'astro-d2';
import starlightSidebarTopics from 'starlight-sidebar-topics';
import starlightBlog from 'starlight-blog';
import starlightImageZoom from 'starlight-image-zoom';
import starlightMdTxt from 'starlight-md-txt';
import starlightCopyButton from 'starlight-copy-button';
import starlightCodeblockFullscreen from 'starlight-codeblock-fullscreen';
import starlightCoolerCredit from 'starlight-cooler-credit';
import starlightSiteGraph from 'starlight-site-graph';
import starlightAnnouncement from 'starlight-announcement';

// https://astro.build/config
export default defineConfig({
	markdown: {
		// starlight-image-zoom todavía no soporta el procesador Sätteri de Astro 7
		processor: unified(),
	},
	integrations: [
		astroD2({
			// usa D2.js (WASM) en vez del binario d2 — no requiere instalación del binario
			experimental: { useD2js: true },
			inline: true,
		}),
		starlight({
			title: 'Kateto Docs',
			description: 'Documentación del equipo de voces event-driven de Kateto.',
			logo: {
				src: './src/assets/kateto-logo.svg',
				alt: 'Kateto',
			},
			favicon: '/favicon.svg',
			plugins: [
				starlightSidebarTopics(
					[
						{ id: 'guias', label: 'Guías', link: '/guides/como-usar', items: ['guides/como-usar'] },
						{ id: 'filosofia', label: 'Filosofía', link: '/philosophy/por-que-kateto', items: ['philosophy/por-que-kateto'] },
						{ id: 'arquitectura', label: 'Arquitectura', link: '/architecture/overview', items: ['architecture/overview', 'architecture/plugin-manager', 'architecture/event-system', 'architecture/config', 'architecture/design-decisions'] },
						{ id: 'plugins', label: 'Plugins', link: '/plugins/overview', items: ['plugins/overview', 'plugins/audio-input', 'plugins/audio-processor', 'plugins/audio-output', 'plugins/executors', 'plugins/voice-manager', 'plugins/system', 'plugins/connectors'] },
						{ id: 'voces', label: 'Voces', link: '/voices/overview', items: ['voices/overview', 'voices/voice-agent', 'voices/skills-and-mcp', 'voices/workflows', 'voices/voice-evolution', 'voices/backlog', 'voices/voice-list-future'] },
						{ id: 'runtime', label: 'Runtime', link: '/runtime/headless', items: ['runtime/headless', 'runtime/overlay', 'runtime/pipeline', 'runtime/run-mode-spec'] },
						{ id: 'desarrollo', label: 'Desarrollo', link: '/development/tdd', items: ['development/tdd', 'development/tooling', 'development/build-week', 'development/final-assessment', 'development/agent', 'development/system-mcp-architecture', 'development/spec2-plan', 'development/future-plugins'] },
						{ id: 'bugs', label: 'Bugs', link: '/bugs/overview', items: ['bugs/overview', 'bugs/known-issues'] },
					],
					{
						exclude: ['/blog/**'],
						topics: {
							desarrollo: ['/development/spec-*'],
							bugs: ['/bugs/*'],
						},
					}
				),
				starlightBlog({
					title: 'Blog de Kateto',
					authors: {
						kateto: { name: 'Kateto', title: 'Equipo de voces' },
					},
				}),
				starlightImageZoom(),
				starlightMdTxt(),
				starlightCopyButton(),
				starlightCodeblockFullscreen(),
				starlightCoolerCredit(),
				starlightSiteGraph(),
				starlightAnnouncement({
					announcements: [
						{
							id: 'docs-launch',
							content: '🎉 <strong>Nuevo sitio de documentación</strong> — bienvenido a las docs de Kateto.',
							variant: 'tip',
						},
					],
				}),
			],
		}),
	],
});
