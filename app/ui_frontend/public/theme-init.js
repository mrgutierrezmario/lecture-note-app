// Loaded by index.html before first paint: apply the saved theme so the page
// never flashes the wrong one.
(function () {
  var stored = null
  try { stored = localStorage.getItem('theme') } catch (e) {}
  var dark = stored === 'dark' ||
    (stored !== 'light' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
})()
