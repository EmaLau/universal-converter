/* Convertitore: tasto destro -> "Converti in" -> formato. Niente build: usa il registro di @nextcloud/files v4
 * (window._nc_files_scope.v4_0), lo stesso che usa registerFileAction(). */
(function () {
	'use strict'
	const stateEl = document.getElementById('initial-state-convertitore-formats')
	if (!stateEl) return
	let F
	try { F = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(stateEl.value), c => c.charCodeAt(0)))) } catch (e) { return }
	const inputs = F.inputs || {}
	if (!Object.keys(inputs).length) return

	const scope = (window._nc_files_scope ??= {})
	const g = (scope.v4_0 ??= {})
	g.fileActions ??= new Map()
	function register(action) {
		if (g.fileActions.has(action.id)) return
		g.fileActions.set(action.id, action)
		if (g.registry && typeof g.registry.dispatchEvent === 'function') {
			g.registry.dispatchEvent(new CustomEvent('register:action', { detail: action }))
		}
	}

	const NAMES = { docx: 'Word', doc: 'Word 97', xlsx: 'Excel', xls: 'Excel 97', pptx: 'PowerPoint', ppt: 'PowerPoint 97', md: 'Markdown', txt: 'Testo', tex: 'LaTeX', azw3: 'Kindle' }
	const ALIAS = { jpeg: 'jpg', jfif: 'jpg', tif: 'tiff', htm: 'html', markdown: 'md', tgz: 'tar.gz', tbz2: 'tar.bz2', txz: 'tar.xz', heif: 'heic' }
	const extOf = name => {
		const l = (name || '').toLowerCase()
		for (const c of ['tar.gz', 'tar.bz2', 'tar.xz']) if (l.endsWith('.' + c)) return c
		const e = l.includes('.') ? l.split('.').pop() : ''
		return ALIAS[e] || e
	}
	const targetsOf = node => (node && node.type === 'file' && (node.permissions & 1)) ? (inputs[extOf(node.basename)] || []) : []
	const label = t => t.toUpperCase() + (NAMES[t] ? ` (${NAMES[t]})` : '')

	// ---- avvisi (OCP.Toast non esiste piu' in NC 35)
	let toastBox
	function toast(text, kind = 'info', ms = 6000) {
		if (!toastBox) {
			toastBox = document.createElement('div')
			toastBox.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:100000;display:flex;flex-direction:column;gap:8px;max-width:min(420px,calc(100vw - 32px))'
			document.body.appendChild(toastBox)
		}
		const colors = { info: 'var(--color-primary-element,#0082c9)', success: 'var(--color-success,#2d7b41)', error: 'var(--color-error,#db0606)' }
		const t = document.createElement('div')
		t.setAttribute('role', kind === 'error' ? 'alert' : 'status')
		t.style.cssText = `background:var(--color-main-background,#fff);color:var(--color-main-text,#222);border-left:4px solid ${colors[kind]};border-radius:var(--border-radius-large,10px);box-shadow:0 2px 12px rgba(0,0,0,.25);padding:10px 14px;font-size:14px;line-height:1.4;cursor:pointer;word-break:break-word`
		t.textContent = text
		t.onclick = () => t.remove()
		toastBox.appendChild(t)
		if (ms) setTimeout(() => t.remove(), ms)
		return t
	}

	const url = p => (window.OC && OC.generateUrl ? OC.generateUrl(p) : '/index.php' + p)
	const token = () => (window.OC && OC.requestToken) || document.head.dataset.requesttoken || ''
	async function api(method, path, body) {
		const r = await fetch(url('/apps/convertitore' + path), {
			method,
			headers: { 'Content-Type': 'application/json', requesttoken: token(), 'OCS-APIRequest': 'true' },
			body: body ? JSON.stringify(body) : undefined,
			credentials: 'same-origin',
		})
		let d = {}
		try { d = await r.json() } catch (e) { /* risposta vuota */ }
		if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`)
		return d
	}

	function showNewFile(src, ctx, r) {
		try {
			if (!ctx.folder || r.parentId !== ctx.folder.fileid || !window._nc_event_bus) return
			const node = new src.constructor({
				id: r.fileId,
				source: ctx.folder.source.replace(/\/$/, '') + '/' + encodeURIComponent(r.name),
				root: src.root,
				owner: src.owner,
				mime: r.mime,
				size: r.size,
				mtime: new Date(r.mtime * 1000),
				permissions: ctx.folder.permissions,
				attributes: {},
			})
			window._nc_event_bus.emit('files:node:created', node)
		} catch (e) {
			console.debug('convertitore: aggiorna la cartella per vedere il file', e)
		}
	}

	async function convert(node, target, ctx) {
		const name = node.basename
		const wait = toast(`Converto «${name}» in ${target.toUpperCase()}…`, 'info', 0)
		try {
			const { job } = await api('POST', '/convert', { fileId: node.fileid, target })
			let delay = 1500
			for (;;) {
				await new Promise(res => setTimeout(res, delay))
				delay = Math.min(delay + 500, 5000)
				let r
				try { r = await api('GET', '/status/' + job) } catch (e) {
					if (/HTTP 5\d\d|Failed to fetch|NetworkError/.test(e.message)) continue
					throw e
				}
				if (r.state === 'done') {
					wait.remove()
					toast(`Creato «${r.name}»` + (r.note ? ` (${r.note})` : ''), 'success')
					showNewFile(node, ctx, r)
					return
				}
				if (r.state === 'error') throw new Error(r.error || 'errore')
				const pct = typeof r.progress === 'number' && r.progress > 0 && r.progress < 1 ? ` ${Math.round(r.progress * 100)}%` : ''
				wait.textContent = r.state === 'queued'
					? `«${name}»: in coda${r.position > 1 ? ` (posizione ${r.position})` : ''}…`
					: `«${name}» → ${target.toUpperCase()}${pct}${r.step ? ' · ' + r.step : ''}`
			}
		} catch (e) {
			wait.remove()
			toast(`Conversione di «${name}» non riuscita: ${e.message}`, 'error', 15000)
		}
	}

	const ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="currentColor" d="M6.99 11 3 15l3.99 4v-3H14v-2H6.99v-3zM21 9l-3.99-4v3H10v2h7.01v3L21 9z"/></svg>'
	const FILE_ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="currentColor" d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm4 18H6V4h7v5h5v11z"/></svg>'
	const common = nodes => nodes.map(targetsOf).reduce((a, b) => a.filter(x => b.includes(x)))

	register({
		id: 'convertitore',
		displayName: () => 'Converti in…',
		iconSvgInline: () => ICON,
		order: 30,
		enabled: ctx => !!ctx.nodes && ctx.nodes.length > 0 && common(ctx.nodes).length > 0,
		exec: async () => null,
		execBatch: async ctx => ctx.nodes.map(() => null),
	})

	const all = []
	for (const list of Object.values(inputs)) for (const t of list) if (!all.includes(t)) all.push(t)
	const rank = Object.keys(F.categories || {})  // ordine del server: documenti, fogli, ..., immagini, audio, video
	all.sort((a, b) => (rank.indexOf(a) + 1 || 999) - (rank.indexOf(b) + 1 || 999))
	all.forEach((t, i) => register({
		id: 'convertitore-' + t.replace(/\W/g, '-'),
		parent: 'convertitore',
		displayName: () => label(t),
		iconSvgInline: () => FILE_ICON,
		order: i,
		enabled: ctx => !!ctx.nodes && ctx.nodes.length > 0 && common(ctx.nodes).includes(t),
		exec: async ctx => { convert(ctx.nodes[0], t, ctx); return null },
		execBatch: async ctx => { ctx.nodes.forEach(n => convert(n, t, ctx)); return ctx.nodes.map(() => null) },
	}))
})()
