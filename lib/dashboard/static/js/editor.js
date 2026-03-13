/* ============================================
   Monaco Editor - Initialization & Mode Switching
   ============================================ */

(function () {
  'use strict';

  var editor = null;
  var currentMode = 'strategy';
  var currentFile = null;
  var openTabs = [];

  // --- Editor Initialization ---

  function initEditor() {
    var container = document.getElementById('editor-container');
    if (!container) return;

    require.config({
      paths: {
        vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs'
      }
    });

    require(['vs/editor/editor.main'], function () {
      editor = monaco.editor.create(container, {
        value: '// Select a file or template to begin editing\n',
        language: 'python',
        theme: 'vs-dark',
        automaticLayout: true,
        minimap: { enabled: true },
        fontSize: 14,
        lineNumbers: 'on',
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        tabSize: 4,
        insertSpaces: true,
        renderWhitespace: 'selection',
        bracketPairColorization: { enabled: true }
      });

      loadModeContent(currentMode);
    });
  }

  // --- Mode Switching ---

  function switchMode(mode) {
    currentMode = mode;
    openTabs = [];
    currentFile = null;

    // Update mode selector UI
    var buttons = document.querySelectorAll('[data-mode]');
    buttons.forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    // Toggle sidebar visibility (file tree only in module mode)
    var sidebar = document.getElementById('file-tree-sidebar');
    if (sidebar) {
      sidebar.style.display = mode === 'module' ? 'block' : 'none';
    }

    // Toggle run button (module mode only)
    var runBtn = document.getElementById('btn-run');
    if (runBtn) {
      runBtn.style.display = mode === 'module' ? 'inline-flex' : 'none';
    }

    // Toggle template picker (strategy mode only)
    var tplPicker = document.getElementById('template-picker');
    if (tplPicker) {
      tplPicker.style.display = mode === 'strategy' ? 'inline-flex' : 'none';
    }

    // Clear tabs
    var tabBar = document.getElementById('editor-tabs');
    if (tabBar) {
      tabBar.innerHTML = '';
    }

    loadModeContent(mode);
  }

  function loadModeContent(mode) {
    switch (mode) {
      case 'strategy':
        loadTemplates();
        loadFile('/api/strategy/source');
        break;
      case 'portfolio':
        loadFile('/api/portfolio/source');
        break;
      case 'module':
        loadModules();
        break;
    }
  }

  // --- File Operations ---

  function loadFile(path) {
    currentFile = path;

    fetch(path)
      .then(function (res) {
        if (!res.ok) throw new Error('Failed to load file: ' + res.status);
        return res.json();
      })
      .then(function (data) {
        if (editor) {
          var content = data.content || data.source || '';
          var language = detectLanguage(path);
          var model = monaco.editor.createModel(content, language);
          editor.setModel(model);
        }
        if (typeof showToast === 'function') {
          showToast('File loaded', 'info');
        }
      })
      .catch(function (err) {
        console.error(err);
        if (typeof showToast === 'function') {
          showToast(err.message, 'error');
        }
      });
  }

  function saveFile() {
    if (!editor || !currentFile) {
      if (typeof showToast === 'function') {
        showToast('No file to save', 'warning');
      }
      return;
    }

    var content = editor.getValue();
    var endpoint = currentFile;

    // Determine save endpoint based on mode
    if (currentMode === 'strategy') {
      endpoint = '/api/strategy/source';
    } else if (currentMode === 'portfolio') {
      endpoint = '/api/portfolio/source';
    }

    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: content, path: currentFile })
    })
      .then(function (res) {
        if (!res.ok) throw new Error('Save failed: ' + res.status);
        return res.json();
      })
      .then(function () {
        if (typeof showToast === 'function') {
          showToast('File saved successfully', 'success');
        }
      })
      .catch(function (err) {
        console.error(err);
        if (typeof showToast === 'function') {
          showToast(err.message, 'error');
        }
      });
  }

  // --- Module Mode ---

  function loadModules() {
    fetch('/api/modules/tree')
      .then(function (res) {
        if (!res.ok) throw new Error('Failed to load modules');
        return res.json();
      })
      .then(function (data) {
        renderFileTree(data.tree || data);
      })
      .catch(function (err) {
        console.error(err);
        if (typeof showToast === 'function') {
          showToast(err.message, 'error');
        }
      });
  }

  function renderFileTree(tree) {
    var sidebar = document.getElementById('file-tree-sidebar');
    if (!sidebar) return;

    sidebar.innerHTML = '';
    renderTreeNode(tree, sidebar, 0);
  }

  function renderTreeNode(node, parent, depth) {
    if (Array.isArray(node)) {
      node.forEach(function (child) {
        renderTreeNode(child, parent, depth);
      });
      return;
    }

    var item = document.createElement('div');
    item.className = 'file-tree-item' + (node.children ? ' directory' : '');
    item.style.paddingLeft = (0.75 + depth * 1) + 'rem';

    var icon = document.createElement('span');
    icon.className = 'icon';
    icon.textContent = node.children ? '\u25B6' : '\u25CB';

    var name = document.createElement('span');
    name.textContent = node.name;

    item.appendChild(icon);
    item.appendChild(name);
    parent.appendChild(item);

    if (node.children) {
      var children = document.createElement('div');
      children.className = 'file-tree-children';

      item.addEventListener('click', function () {
        children.classList.toggle('collapsed');
        icon.textContent = children.classList.contains('collapsed') ? '\u25B6' : '\u25BC';
      });

      renderTreeNode(node.children, children, depth + 1);
      parent.appendChild(children);
    } else {
      item.addEventListener('click', function () {
        // Deactivate other items
        document.querySelectorAll('.file-tree-item.active').forEach(function (el) {
          el.classList.remove('active');
        });
        item.classList.add('active');

        var filePath = node.path || node.name;
        addTab(filePath, node.name);
        loadFile('/api/modules/file?path=' + encodeURIComponent(filePath));
      });
    }
  }

  // --- Tabbed Editing ---

  function addTab(path, name) {
    var tabBar = document.getElementById('editor-tabs');
    if (!tabBar) return;

    // Check if tab already open
    var existing = openTabs.find(function (t) { return t.path === path; });
    if (existing) {
      activateTab(path);
      return;
    }

    openTabs.push({ path: path, name: name });

    var tab = document.createElement('button');
    tab.className = 'editor-tab';
    tab.dataset.path = path;
    tab.textContent = name;

    tab.addEventListener('click', function () {
      activateTab(path);
      loadFile('/api/modules/file?path=' + encodeURIComponent(path));
    });

    tabBar.appendChild(tab);
    activateTab(path);
  }

  function activateTab(path) {
    document.querySelectorAll('.editor-tab').forEach(function (tab) {
      tab.classList.toggle('active', tab.dataset.path === path);
    });
  }

  // --- Run Module ---

  function runModule() {
    if (!editor || !currentFile) {
      if (typeof showToast === 'function') {
        showToast('No module selected', 'warning');
      }
      return;
    }

    var output = document.getElementById('output-panel');
    if (output) {
      output.textContent = 'Running...\n';
    }

    fetch('/api/modules/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: currentFile, content: editor.getValue() })
    })
      .then(function (res) {
        if (!res.ok) throw new Error('Run failed: ' + res.status);
        return res.json();
      })
      .then(function (data) {
        if (output) {
          output.textContent = '';
          if (data.stdout) output.textContent += data.stdout;
          if (data.stderr) {
            var errLine = document.createElement('span');
            errLine.className = 'line-error';
            errLine.textContent = data.stderr;
            output.appendChild(errLine);
          }
          if (data.output) output.textContent += data.output;
        }
        var exitType = (data.exit_code === 0) ? 'success' : 'error';
        if (typeof showToast === 'function') {
          showToast(
            data.exit_code === 0 ? 'Module executed successfully' : 'Module exited with code ' + data.exit_code,
            exitType
          );
        }
      })
      .catch(function (err) {
        console.error(err);
        if (output) output.textContent = 'Error: ' + err.message + '\n';
        if (typeof showToast === 'function') {
          showToast(err.message, 'error');
        }
      });
  }

  // --- Strategy Templates ---

  function loadTemplates() {
    var picker = document.getElementById('template-picker');
    if (!picker) return;

    fetch('/api/strategy/templates')
      .then(function (res) {
        if (!res.ok) throw new Error('Failed to load templates');
        return res.json();
      })
      .then(function (data) {
        var templates = data.templates || data;
        picker.innerHTML = '<option value="">-- Select Template --</option>';
        templates.forEach(function (tpl) {
          var opt = document.createElement('option');
          opt.value = tpl.id || tpl.name;
          opt.textContent = tpl.name || tpl.id;
          picker.appendChild(opt);
        });

        picker.addEventListener('change', function () {
          if (!picker.value) return;
          fetch('/api/strategy/templates/' + encodeURIComponent(picker.value))
            .then(function (res) { return res.json(); })
            .then(function (data) {
              if (editor) {
                editor.setValue(data.content || data.source || '');
              }
            })
            .catch(function (err) {
              console.error(err);
              if (typeof showToast === 'function') {
                showToast('Failed to load template', 'error');
              }
            });
        });
      })
      .catch(function (err) {
        console.error(err);
      });
  }

  // --- Helpers ---

  function detectLanguage(path) {
    if (path.indexOf('.py') !== -1) return 'python';
    if (path.indexOf('.js') !== -1) return 'javascript';
    if (path.indexOf('.json') !== -1) return 'json';
    if (path.indexOf('.yaml') !== -1 || path.indexOf('.yml') !== -1) return 'yaml';
    if (path.indexOf('.toml') !== -1) return 'toml';
    if (path.indexOf('.md') !== -1) return 'markdown';
    return 'python';
  }

  // --- Keyboard Shortcuts ---

  document.addEventListener('keydown', function (e) {
    // Ctrl/Cmd + S to save
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      saveFile();
    }
  });

  // --- Expose Public API ---

  window.EditorApp = {
    init: initEditor,
    switchMode: switchMode,
    loadFile: loadFile,
    saveFile: saveFile,
    runModule: runModule,
    loadTemplates: loadTemplates,
    loadModules: loadModules
  };

  // Auto-init when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initEditor);
  } else {
    initEditor();
  }
})();
