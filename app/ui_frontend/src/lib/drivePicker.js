// Google's folder picker, loaded on demand. Resolves with { id, name } of the
// folder the user chose, or null if they cancelled. The picker is created with
// the user's own access token and the app's id, which is what makes the chosen
// folder accessible to the app under the narrow drive.file permission.
let gapiPromise = null

function loadPickerApi() {
  if (gapiPromise) return gapiPromise
  gapiPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = 'https://apis.google.com/js/api.js'
    script.async = true
    script.onload = () => window.gapi.load('picker', { callback: resolve, onerror: reject })
    script.onerror = () => reject(new Error('Could not load Google\'s picker'))
    document.head.appendChild(script)
  })
  return gapiPromise
}

export async function pickDriveFolder() {
  const response = await fetch('/api/drive/picker-token')
  const creds = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(creds.detail || `HTTP ${response.status}`)
  await loadPickerApi()
  const { google } = window
  return new Promise((resolve) => {
    const view = new google.picker.DocsView(google.picker.ViewId.FOLDERS)
      .setIncludeFolders(true)
      .setSelectFolderEnabled(true)
      .setMimeTypes('application/vnd.google-apps.folder')
    const picker = new google.picker.PickerBuilder()
      .setTitle('Choose the folder for your lectures')
      .setOAuthToken(creds.access_token)
      .setDeveloperKey(creds.api_key)
      .setAppId(creds.app_id)
      .setOrigin(`${window.location.protocol}//${window.location.host}`)
      .addView(view)
      .setCallback((data) => {
        if (data.action === google.picker.Action.PICKED) {
          const doc = data.docs?.[0]
          resolve(doc ? { id: doc.id, name: doc.name } : null)
        } else if (data.action === google.picker.Action.CANCEL) {
          resolve(null)
        }
      })
      .build()
    picker.setVisible(true)
  })
}
