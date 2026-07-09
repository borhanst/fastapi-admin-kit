/* ═══════════════════════════════════════════════════════════════════════════
   FastAPI Admin Kit — Alpine.js Stores & Components
   Warm Editorial Brutalism
   ═══════════════════════════════════════════════════════════════════════════ */

document.addEventListener('alpine:init', () => {

  /* ── navGroup (sidebar collapsible sections) ─────────────────────── */

  Alpine.data('navGroup', (tag, defaultCollapsed) => ({
    collapsed: false,

    init() {
      const saved = localStorage.getItem('admin-nav-group:' + tag)
      if (saved !== null) {
        this.collapsed = saved === '1'
      } else {
        this.collapsed = defaultCollapsed
      }
      if (this.$el && this.$el.querySelector('.active')) {
        this.collapsed = false
      }
    },

    toggle() {
      this.collapsed = !this.collapsed
      localStorage.setItem('admin-nav-group:' + tag, this.collapsed ? '1' : '0')
    },
  }))

  /* ── Theme store ─────────────────────────────────────────────────── */

  Alpine.store('theme', {
    dark: JSON.parse(localStorage.getItem('admin_dark_mode') ?? 'false'),

    toggle() {
      this.dark = !this.dark;
      this._apply();
    },

    _apply() {
      localStorage.setItem('admin_dark_mode', JSON.stringify(this.dark));
      document.documentElement.setAttribute('data-theme', this.dark ? 'dark' : 'light');
    },

    init() {
      this._apply();
    },
  });

  /* ── Themes store (preset switching) ─────────────────── */

  Alpine.store('themes', {
    preset: localStorage.getItem('admin_theme_preset') || 'editorial',

    apply(name) {
      this.preset = name;
      document.documentElement.setAttribute('data-preset', name);
      localStorage.setItem('admin_theme_preset', name);
      window.dispatchEvent(new CustomEvent('theme-change', { detail: { preset: name } }));
    },

    init() {
      const saved = localStorage.getItem('admin_theme_preset');
      if (saved) {
        document.documentElement.setAttribute('data-preset', saved);
        this.preset = saved;
      }
    },
  });

  /* ── Relation Picker ─────────────────────────────────────────────── */

  Alpine.data('relationPicker', (initialId, initialLabel, searchUrl) => ({
    selectedId: initialId || '',
    searchQuery: initialLabel || '',
    results: [],
    open: false,
    _debounce: null,

    async search() {
      clearTimeout(this._debounce);
      this._debounce = setTimeout(async () => {
        if (this.searchQuery.length < 1) {
          this.results = [];
          return;
        }
        try {
          const resp = await fetch(`${searchUrl}?q=${encodeURIComponent(this.searchQuery)}`);
          if (resp.ok) {
            this.results = await resp.json();
          }
        } catch (e) {
          console.error('Relation search error:', e);
        }
      }, 250);
    },

    select(result) {
      this.selectedId = result.id;
      this.searchQuery = result.label;
      this.results = [];
      this.open = false;
    },

    clear() {
      this.selectedId = '';
      this.searchQuery = '';
      this.results = [];
    },
  }));

  /* ── Multi-Relation ──────────────────────────────────────────────── */

  Alpine.data('multiRelation', (initialIds, searchUrl, initialItems) => ({
    selectedIds: [],
    selectedItems: [],
    searchQuery: '',
    results: [],
    open: false,
    _debounce: null,

    init() {
      if (Array.isArray(initialIds)) {
        this.selectedIds = initialIds;
      } else if (typeof initialIds === 'string' && initialIds) {
        try { this.selectedIds = JSON.parse(initialIds); } catch (e) { this.selectedIds = []; }
      }
      if (Array.isArray(initialItems)) {
        this.selectedItems = initialItems;
      } else if (typeof initialItems === 'string' && initialItems) {
        try { this.selectedItems = JSON.parse(initialItems); } catch (e) { this.selectedItems = []; }
      }
      if (this.selectedIds.length > 0 && this.selectedItems.length === 0) {
        this._loadSelected();
      }
      const self = this;
      this.$nextTick(() => {
        const input = self.$el.querySelector('input[type="text"]');
        if (input) {
          input.addEventListener('focus', () => {
            self.open = true;
            self.search();
          });
        }
      });
    },

    _ensureArray(val) {
      if (Array.isArray(val)) return val;
      if (typeof val === 'string' && val) {
        try { return JSON.parse(val); } catch (e) { return []; }
      }
      return [];
    },

    async _loadSelected() {
      try {
        const ids = this._ensureArray(this.selectedIds);
        const resp = await fetch(`${searchUrl}?ids=${ids.join(',')}`);
        if (resp.ok) {
          this.selectedItems = await resp.json();
        }
      } catch (e) {
        console.error('Multi-relation load error:', e);
      }
    },

    async search() {
      clearTimeout(this._debounce);
      this._debounce = setTimeout(async () => {
        try {
          const q = this.searchQuery.trim();
          const url = q ? `${searchUrl}?q=${encodeURIComponent(q)}` : `${searchUrl}`;
          const resp = await fetch(url);
          if (resp.ok) {
            const all = await resp.json();
            const ids = this._ensureArray(this.selectedIds);
            const idStrs = ids.map(String);
            this.results = all.filter(r => !idStrs.includes(String(r.id)));
          }
        } catch (e) {
          console.error('Multi-relation search error:', e);
        }
      }, 250);
    },

    add(result) {
      const ids = this._ensureArray(this.selectedIds);
      const idStrs = ids.map(String);
      if (!idStrs.includes(String(result.id))) {
        this.selectedIds.push(result.id);
        this.selectedItems.push(result);
      }
      this.searchQuery = '';
      this.results = [];
    },

    remove(index) {
      this.selectedIds.splice(index, 1);
      this.selectedItems.splice(index, 1);
    },
  }));

  /* ── Permission Widget ────────────────────────────────────────────── */

  Alpine.data('permissionWidget', (searchUrl, initialPermData) => ({
    selectedTables: [],
    searchQuery: '',
    results: [],
    open: false,
    _debounce: null,
    permData: {},
    expandedTable: null,

    init() {
      this.permData = initialPermData || {};
      this.selectedTables = Object.keys(this.permData).map(k => ({
        id: k, label: this.permData[k]._label || k
      }));
    },

    async search() {
      clearTimeout(this._debounce);
      this._debounce = setTimeout(async () => {
        try {
          const q = this.searchQuery.trim();
          const url = q ? `${searchUrl}?q=${encodeURIComponent(q)}` : searchUrl;
          const resp = await fetch(url);
          if (resp.ok) {
            const all = await resp.json();
            const selected = new Set(this.selectedTables.map(t => t.id));
            this.results = all.filter(r => !selected.has(r.id));
          }
        } catch (e) { console.error('Permission search error:', e); }
      }, 250);
    },

    addTable(table) {
      if (!this.permData[table.id]) {
        this.permData[table.id] = {
          _label: table.label,
          view: false, create: false, edit: false, delete: false
        };
      }
      this.selectedTables.push(table);
      this.searchQuery = '';
      this.results = [];
      this.expandedTable = table.id;
    },

    removeTable(index) {
      const table = this.selectedTables[index];
      delete this.permData[table.id];
      this.selectedTables.splice(index, 1);
      if (this.expandedTable === table.id) this.expandedTable = null;
    },

    toggleExpand(tableId) {
      this.expandedTable = this.expandedTable === tableId ? null : tableId;
    },

    toggleAllActions(tableId, on) {
      this.permData[tableId].view = on;
      this.permData[tableId].create = on;
      this.permData[tableId].edit = on;
      this.permData[tableId].delete = on;
    },

    get serializedPermData() {
      const out = {};
      for (const [table, data] of Object.entries(this.permData)) {
        out[table] = { view: data.view, create: data.create, edit: data.edit, delete: data.delete };
      }
      return JSON.stringify(out);
    }
  }));

  /* ── Slug Widget ─────────────────────────────────────────────────── */

  Alpine.data('slugWidget', (sourceField, name) => ({
    slug: '',
    manualEdit: false,

    init() {
      const source = document.getElementById(sourceField);
      if (source) {
        source.addEventListener('input', () => {
          if (!this.manualEdit) {
            this.slug = this._toSlug(source.value);
          }
        });
      }
      const input = document.getElementById(name);
      if (input) {
        this.slug = input.value || '';
      }
    },

    onManualEdit(value) {
      this.manualEdit = value.length > 0;
      this.slug = value;
    },

    regenerate() {
      const source = document.getElementById(sourceField);
      if (source) {
        this.slug = this._toSlug(source.value);
        this.manualEdit = false;
      }
    },

    _toSlug(str) {
      return str
        .toLowerCase()
        .trim()
        .replace(/[^\w\s-]/g, '')
        .replace(/[\s_]+/g, '-')
        .replace(/-+/g, '-')
        .replace(/^-|-$/g, '');
    },
  }));

  /* ── Image Upload ────────────────────────────────────────────────── */

  Alpine.data('imageUpload', (existingUrl) => ({
    existingUrl: existingUrl || '',
    previewUrl: '',
    action: existingUrl ? 'keep' : 'none',

    onFileSelect(event) {
      const file = event.target.files[0];
      if (!file) return;
      this.action = 'replace';
      const reader = new FileReader();
      reader.onload = (e) => {
        this.previewUrl = e.target.result;
      };
      reader.readAsDataURL(file);
    },

    clear() {
      this.previewUrl = '';
      this.existingUrl = '';
      this.action = 'remove';
      const input = this.$refs.fileInput;
      if (input) input.value = '';
    },
  }));

  /* ── File Upload ─────────────────────────────────────────────────── */

  Alpine.data('fileUpload', (existingUrl) => ({
    existingUrl: existingUrl || '',
    fileName: '',
    action: existingUrl ? 'keep' : 'none',

    onFileSelect(event) {
      const file = event.target.files[0];
      if (!file) return;
      this.fileName = file.name;
      this.action = 'replace';
    },

    clear() {
      this.fileName = '';
      this.action = 'remove';
      const input = this.$refs.fileInput;
      if (input) input.value = '';
    },
  }));

  /* ── Tag Input ───────────────────────────────────────────────────── */

  Alpine.data('tagInput', (initialTags) => ({
    tags: initialTags || [],
    newTag: '',

    add() {
      const tag = this.newTag.trim();
      if (tag && !this.tags.includes(tag)) {
        this.tags.push(tag);
      }
      this.newTag = '';
    },

    remove(index) {
      this.tags.splice(index, 1);
    },
  }));

  /* ── Autocomplete Field ──────────────────────────────────────────── */

  Alpine.data('autocompleteField', (suggestions, initialValue) => ({
    query: initialValue || '',
    open: false,
    filtered: [],
    highlighted: -1,
    allSuggestions: suggestions || [],

    onInput() {
      const q = this.query.toLowerCase().trim();
      this.highlighted = -1;
      if (q.length > 0) {
        this.filtered = this.allSuggestions.filter(s =>
          s.toLowerCase().includes(q)
        );
        this.open = this.filtered.length > 0;
      } else {
        this.filtered = [];
        this.open = false;
      }
    },

    onFocus() {
      const q = this.query.toLowerCase().trim();
      if (q.length > 0) {
        this.filtered = this.allSuggestions.filter(s =>
          s.toLowerCase().includes(q)
        );
        this.open = this.filtered.length > 0;
      }
    },

    selectItem(item) {
      this.query = item;
      this.filtered = [];
      this.open = false;
      this.highlighted = -1;
    },

    clearSelection() {
      this.query = '';
      this.filtered = [];
      this.open = false;
      this.highlighted = -1;
    },

    onArrowDown() {
      if (this.highlighted < this.filtered.length - 1) {
        this.highlighted++;
      }
    },

    onArrowUp() {
      if (this.highlighted > 0) {
        this.highlighted--;
      }
    },

    onEnter() {
      if (this.highlighted >= 0 && this.highlighted < this.filtered.length) {
        this.selectItem(this.filtered[this.highlighted]);
      } else if (this.filtered.length > 0) {
        this.selectItem(this.filtered[0]);
      }
    },
  }));

  /* ── Row Selection ─────────────────────────────────────────────── */

  Alpine.data('rowSelect', () => ({
    selected: [],

    isSelected(id) {
      return this.selected.includes(id)
    },

    toggle(id) {
      if (this.isSelected(id)) {
        this.selected = this.selected.filter(i => i !== id)
      } else {
        this.selected.push(id)
      }
    },

    toggleAll() {
      const checkboxes = this.$root.querySelectorAll('input[name="ids[]"]')
      const allIds = Array.from(checkboxes).map(cb => cb.value)
      if (this.selected.length === allIds.length) {
        this.selected = []
      } else {
        this.selected = [...allIds]
      }
    },

    get allSelected() {
      const checkboxes = this.$root.querySelectorAll('input[name="ids[]"]')
      return checkboxes.length > 0 && this.selected.length === checkboxes.length
    },

    get someSelected() {
      return this.selected.length > 0 && !this.allSelected
    },
  }))

  /* ── Delete Confirm Modal ────────────────────────────────────────── */

  Alpine.data('deleteConfirm', () => ({
    open: false,

    openModal() {
      this.open = true
    },

    confirm() {
      this.open = false
      this.$nextTick(() => this.$refs.submitBtn.click())
    },

    cancel() {
      this.open = false
    },
  }))

  /* ── Command Palette (global search) ──────────────────────────────── */

  Alpine.data('commandPalette', () => ({
    open: false,
    query: '',
    results: [],
    selectedIndex: 0,
    _debounce: null,

    init() {
      window.addEventListener('open-command-palette', () => {
        this.open = true;
        this.$nextTick(() => {
          const input = this.$refs.paletteInput;
          if (input) { input.focus(); input.select(); }
        });
      });

      document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
          e.preventDefault();
          this.open = !this.open;
          if (this.open) {
            this.$nextTick(() => {
              const input = this.$refs.paletteInput;
              if (input) { input.focus(); input.select(); }
            });
          }
        }
      });
    },

    close() {
      this.open = false;
      this.query = '';
      this.results = [];
      this.selectedIndex = 0;
    },

    onInput() {
      clearTimeout(this._debounce);
      this._debounce = setTimeout(() => this.search(), 200);
    },

    async search() {
      const q = this.query.trim();
      if (!q) {
        this.results = [];
        this.selectedIndex = 0;
        return;
      }
      try {
        const resp = await fetch(`/admin/search/suggestions?q=${encodeURIComponent(q)}`);
        if (resp.ok) {
          const data = await resp.json();
          this.results = data.suggestions || [];
          this.selectedIndex = 0;
        }
      } catch (e) {
        console.error('Command palette search error:', e);
      }
    },

    onKeydown(e) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        this.selectedIndex = Math.min(this.selectedIndex + 1, this.results.length - 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        this.selectedIndex = Math.max(this.selectedIndex - 1, 0);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (this.results[this.selectedIndex]) {
          this.navigate(this.results[this.selectedIndex].url);
        }
      } else if (e.key === 'Escape') {
        this.close();
      }
    },

    navigate(url) {
      this.close();
      window.location.href = url;
    },
  }));

  /* ── JSON Editor ─────────────────────────────────────────────────── */

  Alpine.data('jsonEditor', (textareaId) => ({
    editor: null,

    init() {
      const textarea = document.getElementById(textareaId);
      if (!textarea) return;

      const container = this.$refs.editorContainer;
      if (!container) return;

      if (typeof CodeMirror !== 'undefined') {
        this.editor = CodeMirror(container, {
          value: textarea.value || '{}',
          mode: 'application/json',
          theme: 'default',
          lineNumbers: true,
          lineWrapping: true,
          tabSize: 2,
          matchBrackets: true,
          autoCloseBrackets: true,
        });

        this.editor.on('change', () => {
          textarea.value = this.editor.getValue();
        });
      } else {
        /* Fallback: plain textarea */
        const fallback = document.createElement('textarea');
        fallback.id = textareaId + '_fallback';
        fallback.name = textarea.name;
        fallback.value = textarea.value;
        fallback.className = 'form-input w-full';
        fallback.style.minHeight = '200px';
        fallback.style.fontFamily = 'var(--font-mono)';
        fallback.style.resize = 'vertical';
        container.appendChild(fallback);
        textarea.type = 'hidden';
      }
    },
  }));

});

/* ── HTMX Loading Bar ────────────────────────────────────────────── */

(function() {
  var loadingBar = document.getElementById('loading-bar');
  if (!loadingBar) return;

  document.addEventListener('htmx:beforeRequest', function(e) {
    loadingBar.style.transform = 'scaleX(0.3)';
    loadingBar.style.transition = 'transform 300ms cubic-bezier(0.16, 1, 0.3, 1)';
  });

  document.addEventListener('htmx:afterRequest', function(e) {
    loadingBar.style.transform = 'scaleX(1)';
    loadingBar.style.transition = 'transform 150ms cubic-bezier(0.4, 0, 1, 1)';
    setTimeout(function() {
      loadingBar.style.transform = 'scaleX(0)';
    }, 150);
  });

  document.addEventListener('htmx:beforeSwap', function(e) {
    loadingBar.style.transform = 'scaleX(0.7)';
  });

  document.addEventListener('htmx:afterSwap', function(e) {
    loadingBar.style.transform = 'scaleX(1)';
    setTimeout(function() {
      loadingBar.style.transform = 'scaleX(0)';
    }, 100);
  });
})();

/* ── Confirm dialog ───────────────────────────────────────────────────── */

function confirmAction(title, message, callback) {
  const dialog = document.getElementById('confirm-dialog');
  if (!dialog) { callback(); return; }
  const data = dialog.__x || dialog._x_dataStack?.[0];
  if (data) {
    data.title = title;
    data.message = message;
    data.onConfirm = callback;
    data.open = true;
  } else {
    callback();
  }
}

// ── Inline Edit Keyboard Support ──────────────────────────────

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    const form = e.target.closest('.inline-edit-form');
    if (form) {
      const cancelBtn = form.querySelector('.inline-edit-cancel');
      if (cancelBtn) cancelBtn.click();
    }
  }
});
