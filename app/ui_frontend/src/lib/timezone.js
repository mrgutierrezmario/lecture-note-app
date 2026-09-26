/**
 * The browser's IANA timezone (e.g. "America/New_York"). PDF, Word and
 * "Save to Google Drive" are built on the server, which can't know where the
 * reader is; these requests send it so the dates print in local time. If the
 * browser can't tell, the server falls back to UTC and says so.
 */
export const browserTz = () => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || ''
  } catch {
    return ''
  }
}

// `?tz=…` query string for export and Drive URLs.
export const tzQuery = () => `tz=${encodeURIComponent(browserTz())}`
