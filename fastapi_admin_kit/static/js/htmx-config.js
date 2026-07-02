/* ═══════════════════════════════════════════════════════════════════════════
   FastAPI Console — HTMX Configuration
   ═══════════════════════════════════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', () => {

  /* ── Default swap style ──────────────────────────────────────────────── */

  if (typeof htmx !== 'undefined') {
    htmx.config.defaultSwapStyle = 'outerHTML';
  }

  /* ── CSRF / HTMX header injection ────────────────────────────────────── */

  document.body.addEventListener('htmx:configRequest', (event) => {
    /* Read CSRF token from meta tag if present */
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) {
      event.detail.headers['X-CSRF-Token'] = meta.getAttribute('content');
    }

    /* Always send the HTMX marker so the server can distinguish HTMX
       requests from full-page navigations. */
    event.detail.headers['HX-Request'] = 'true';
  });

  /* ── Show/hide loading bar on HTMX events ────────────────────────────── */

  const loadingBar = document.getElementById('loading-bar');
  if (loadingBar) {
    document.body.addEventListener('htmx:beforeRequest', () => {
      loadingBar.style.display = 'block';
    });
    document.body.addEventListener('htmx:afterRequest', () => {
      loadingBar.style.display = 'none';
    });
    document.body.addEventListener('htmx:responseError', () => {
      loadingBar.style.display = 'none';
    });
  }

});
