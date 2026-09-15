/**
 * MP3 export in two steps: ask the server to build the file (with progress),
 * then hand the finished URL to the browser's download manager. The direct
 * link alone works too, but the browser shows nothing while the server
 * assembles a long recording — this is what drives the spinner.
 */
export async function prepareMp3(sessionId, onProgress) {
  const url = `/api/session/${sessionId}/export/audio.mp3`
  const post = await fetch(`${url}/prepare`, { method: 'POST' })
  if (!post.ok) {
    const data = await post.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${post.status}`)
  }
  let job = await post.json()
  onProgress?.(job)
  while (job.status === 'building') {
    await new Promise(r => setTimeout(r, 1000))
    const res = await fetch(`${url}/status`)
    job = res.ok ? await res.json() : { status: 'error', error: `HTTP ${res.status}` }
    onProgress?.(job)
  }
  if (job.status !== 'ready') throw new Error(job.error || 'Conversion failed')
  return { url, filename: job.filename }
}

/** Trigger a browser download of an already-prepared URL. */
export function downloadUrl(url, filename) {
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}
