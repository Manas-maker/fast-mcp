from __future__ import annotations

import json
from typing import Any


def get_inspector_html(
    server_name: str = "fast-mcp",
    server_version: str = "0.1.0",
    mount_path: str = "/mcp",
    tools: list[dict[str, Any]] | None = None,
    resources: list[dict[str, Any]] | None = None,
) -> str:
    """Generate self-contained HTML/CSS/JS single-page application for FastMCP Inspector."""
    initial_data = {
        "server": {
            "name": server_name,
            "version": server_version,
            "mountPath": mount_path,
        },
        "tools": tools or [],
        "resources": resources or [],
    }
    initial_data_json = json.dumps(initial_data, separators=(",", ":"))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{server_name} - FastMCP Inspector</title>
  <style>
    :root {{
      --bg-primary: #0f172a;
      --bg-secondary: #1e293b;
      --bg-card: #1e293b;
      --bg-input: #090d16;
      --border: #334155;
      --border-focus: #6366f1;
      --text-primary: #f8fafc;
      --text-secondary: #94a3b8;
      --text-muted: #64748b;
      --accent-primary: #6366f1;
      --accent-hover: #4f46e5;
      --accent-glow: rgba(99, 102, 241, 0.2);
      --badge-app: #10b981;
      --error: #ef4444;
      --success: #10b981;
      --code-font: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }}
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg-primary);
      color: var(--text-primary);
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
    }}
    header {{
      background-color: var(--bg-secondary);
      border-bottom: 1px solid var(--border);
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-shrink: 0;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .logo-badge {{
      background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
      color: #fff;
      font-weight: 800;
      font-size: 14px;
      padding: 4px 8px;
      border-radius: 6px;
      letter-spacing: 0.5px;
    }}
    .title-group h1 {{
      font-size: 16px;
      font-weight: 700;
      letter-spacing: -0.3px;
    }}
    .title-group p {{
      font-size: 12px;
      color: var(--text-secondary);
    }}
    .header-badges {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}
    .badge {{
      font-size: 11px;
      font-weight: 600;
      padding: 3px 8px;
      border-radius: 9999px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.03);
      color: var(--text-secondary);
    }}
    .badge.active {{
      border-color: rgba(16, 185, 129, 0.4);
      color: #34d399;
      background: rgba(16, 185, 129, 0.1);
    }}
    .main-container {{
      display: flex;
      flex: 1;
      height: calc(100vh - 65px);
      overflow: hidden;
    }}
    .sidebar {{
      width: 320px;
      min-width: 280px;
      background-color: var(--bg-secondary);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    .search-box {{
      padding: 12px;
      border-bottom: 1px solid var(--border);
    }}
    .search-box input {{
      width: 100%;
      background: var(--bg-input);
      border: 1px solid var(--border);
      color: var(--text-primary);
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 13px;
      outline: none;
      transition: border-color 0.15s;
    }}
    .search-box input:focus {{
      border-color: var(--border-focus);
    }}
    .tool-list {{
      flex: 1;
      overflow-y: auto;
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    .tool-item {{
      padding: 10px 12px;
      border-radius: 6px;
      cursor: pointer;
      border: 1px solid transparent;
      transition: all 0.15s ease;
    }}
    .tool-item:hover {{
      background: rgba(255, 255, 255, 0.04);
      border-color: var(--border);
    }}
    .tool-item.selected {{
      background: rgba(99, 102, 241, 0.12);
      border-color: var(--accent-primary);
    }}
    .tool-item-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 4px;
    }}
    .tool-name {{
      font-weight: 600;
      font-size: 13px;
      color: var(--text-primary);
      font-family: var(--code-font);
    }}
    .tool-desc {{
      font-size: 12px;
      color: var(--text-secondary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .app-tag {{
      font-size: 9px;
      font-weight: 700;
      text-transform: uppercase;
      padding: 2px 5px;
      border-radius: 4px;
      background: rgba(16, 185, 129, 0.2);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.4);
    }}
    .content-pane {{
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow-y: auto;
      padding: 24px;
      background: var(--bg-primary);
    }}
    .card {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 20px;
    }}
    .card-title {{
      font-size: 14px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-secondary);
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .tool-header-title {{
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 8px;
    }}
    .tool-header-title h2 {{
      font-size: 20px;
      font-family: var(--code-font);
      color: #fff;
    }}
    .tool-description-full {{
      font-size: 14px;
      color: var(--text-secondary);
      margin-bottom: 16px;
      line-height: 1.5;
    }}
    .meta-uri-badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(99, 102, 241, 0.1);
      border: 1px solid var(--accent-primary);
      color: #a5b4fc;
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 12px;
      font-family: var(--code-font);
      margin-bottom: 16px;
    }}
    textarea.json-editor {{
      width: 100%;
      height: 140px;
      background: var(--bg-input);
      border: 1px solid var(--border);
      color: var(--text-primary);
      font-family: var(--code-font);
      font-size: 13px;
      padding: 12px;
      border-radius: 6px;
      resize: vertical;
      outline: none;
      transition: border-color 0.15s;
    }}
    textarea.json-editor:focus {{
      border-color: var(--border-focus);
    }}
    .btn {{
      background: var(--accent-primary);
      color: #fff;
      border: none;
      padding: 10px 18px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      transition: background 0.15s;
    }}
    .btn:hover {{
      background: var(--accent-hover);
    }}
    .btn:disabled {{
      opacity: 0.6;
      cursor: not-allowed;
    }}
    .response-pane {{
      background: var(--bg-input);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      font-family: var(--code-font);
      font-size: 13px;
      color: #e2e8f0;
      white-space: pre-wrap;
      max-height: 280px;
      overflow-y: auto;
    }}
    .schema-pane {{
      background: var(--bg-input);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      font-family: var(--code-font);
      font-size: 12px;
      color: #cbd5e1;
      max-height: 200px;
      overflow-y: auto;
    }}
    .empty-state {{
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100%;
      color: var(--text-muted);
      text-align: center;
      gap: 12px;
    }}
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <span class="logo-badge">⚡ MCP</span>
      <div class="title-group">
        <h1>{server_name} Inspector</h1>
        <p>Embedded FastMCP Visual Testing & SEP-1865 Protocol Explorer</p>
      </div>
    </div>
    <div class="header-badges">
      <span class="badge active" id="status-badge">● Online</span>
      <span class="badge">v{server_version}</span>
      <span class="badge">{mount_path}</span>
      <span class="badge">SEP-1865 Apps</span>
    </div>
  </header>

  <div class="main-container">
    <aside class="sidebar">
      <div class="search-box">
        <input type="text" id="search-input" placeholder="Search tools..." oninput="filterTools()">
      </div>
      <div class="tool-list" id="tool-list">
        <!-- Tools will be rendered here -->
      </div>
    </aside>

    <main class="content-pane" id="content-pane">
      <div class="empty-state" id="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
        </svg>
        <p>Select a tool from the sidebar to inspect its schema and run test calls.</p>
      </div>

      <div id="tool-detail" style="display: none;">
        <div class="card">
          <div class="tool-header-title">
            <h2 id="active-tool-name"></h2>
            <span id="active-tool-tag" class="app-tag" style="display: none;">MCP App</span>
          </div>
          <p id="active-tool-description" class="tool-description-full"></p>
          <div id="active-tool-resource" class="meta-uri-badge" style="display: none;"></div>
        </div>

        <div class="card">
          <div class="card-title">Input Parameters (JSON)</div>
          <textarea id="arguments-editor" class="json-editor" placeholder="{{}}"></textarea>
          <div style="margin-top: 12px; display: flex; gap: 8px;">
            <button class="btn" id="run-btn" onclick="executeSelectedTool()">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3"/>
              </svg>
              Run Tool
            </button>
            <button class="btn" style="background: var(--bg-secondary); border: 1px solid var(--border);" onclick="resetTemplate()">
              Reset Arguments
            </button>
          </div>
        </div>

        <div class="card">
          <div class="card-title">Execution Result</div>
          <pre class="response-pane" id="response-output">Click "Run Tool" to execute and inspect the response.</pre>
        </div>

        <div class="card">
          <div class="card-title">Input Schema</div>
          <pre class="schema-pane" id="schema-output"></pre>
        </div>
      </div>
    </main>
  </div>

  <script>
    window.__INITIAL_DATA__ = {initial_data_json};
    var currentTools = window.__INITIAL_DATA__.tools || [];
    var selectedTool = null;
    var mountPath = window.__INITIAL_DATA__.server.mountPath || "/mcp";

    function filterTools() {{
      var q = document.getElementById("search-input").value.toLowerCase();
      renderTools(currentTools.filter(function(t) {{
        return (t.name || "").toLowerCase().includes(q) || (t.description || "").toLowerCase().includes(q);
      }}));
    }}

    function renderTools(tools) {{
      var container = document.getElementById("tool-list");
      container.innerHTML = "";
      tools.forEach(function(tool) {{
        var item = document.createElement("div");
        item.className = "tool-item" + (selectedTool && selectedTool.name === tool.name ? " selected" : "");
        item.onclick = function() {{ selectTool(tool); }};

        var header = document.createElement("div");
        header.className = "tool-item-header";

        var nameSpan = document.createElement("span");
        nameSpan.className = "tool-name";
        nameSpan.textContent = tool.name;
        header.appendChild(nameSpan);

        var hasApp = tool._meta && tool._meta.ui && tool._meta.ui.resourceUri;
        if (hasApp) {{
          var tag = document.createElement("span");
          tag.className = "app-tag";
          tag.textContent = "APP";
          header.appendChild(tag);
        }}

        var descP = document.createElement("div");
        descP.className = "tool-desc";
        descP.textContent = tool.description || "No description provided.";

        item.appendChild(header);
        item.appendChild(descP);
        container.appendChild(item);
      }});
    }}

    function selectTool(tool) {{
      selectedTool = tool;
      document.getElementById("empty-state").style.display = "none";
      document.getElementById("tool-detail").style.display = "block";

      document.getElementById("active-tool-name").textContent = tool.name;
      document.getElementById("active-tool-description").textContent = tool.description || "No description provided.";

      var hasApp = tool._meta && tool._meta.ui && tool._meta.ui.resourceUri;
      var tagEl = document.getElementById("active-tool-tag");
      var resEl = document.getElementById("active-tool-resource");

      if (hasApp) {{
        tagEl.style.display = "inline-block";
        resEl.style.display = "inline-flex";
        resEl.textContent = "SEP-1865 Resource: " + tool._meta.ui.resourceUri;
      }} else {{
        tagEl.style.display = "none";
        resEl.style.display = "none";
      }}

      var schema = tool.inputSchema || tool.input_schema || {{}};
      document.getElementById("schema-output").textContent = JSON.stringify(schema, null, 2);

      resetTemplate();
      filterTools();
    }}

    function resetTemplate() {{
      if (!selectedTool) return;
      var schema = selectedTool.inputSchema || selectedTool.input_schema || {{}};
      var template = {{}};
      if (schema.properties) {{
        Object.keys(schema.properties).forEach(function(key) {{
          var prop = schema.properties[key];
          if (prop.default !== undefined) {{
            template[key] = prop.default;
          }} else if (prop.type === "string") {{
            template[key] = "";
          }} else if (prop.type === "integer" || prop.type === "number") {{
            template[key] = 0;
          }} else if (prop.type === "boolean") {{
            template[key] = false;
          }} else if (prop.type === "array") {{
            template[key] = [];
          }} else {{
            template[key] = null;
          }}
        }});
      }}
      document.getElementById("arguments-editor").value = JSON.stringify(template, null, 2);
    }}

    async function executeSelectedTool() {{
      if (!selectedTool) return;
      var runBtn = document.getElementById("run-btn");
      var output = document.getElementById("response-output");

      var argsText = document.getElementById("arguments-editor").value.trim();
      var args = {{}};
      if (argsText) {{
        try {{
          args = JSON.parse(argsText);
        }} catch (e) {{
          output.textContent = "Error: Invalid JSON arguments: " + e.message;
          return;
        }}
      }}

      runBtn.disabled = true;
      output.textContent = "Executing tool...";

      // PostMessage bridge notification for SEP-1865 host
      if (window.parent && window.parent !== window) {{
        window.parent.postMessage({{
          jsonrpc: "2.0",
          method: "tools/call",
          params: {{ name: selectedTool.name, arguments: args }}
        }}, "*");
      }}

      try {{
        var resp = await fetch(mountPath + "/docs/call", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ name: selectedTool.name, arguments: args }})
        }});
        var data = await resp.json();
        if (data.is_error) {{
          output.textContent = "Error: " + (data.error || JSON.stringify(data, null, 2));
        }} else {{
          output.textContent = JSON.stringify(data.result !== undefined ? data.result : data, null, 2);
        }}
      }} catch (err) {{
        output.textContent = "Network / execution error: " + err.message;
      }} finally {{
        runBtn.disabled = false;
      }}
    }}

    // SEP-1865 PostMessage Protocol Listener
    window.addEventListener("message", function(evt) {{
      if (!evt.data) return;
      try {{
        var msg = typeof evt.data === "string" ? JSON.parse(evt.data) : evt.data;
        if (msg.jsonrpc === "2.0" && msg.method === "refresh") {{
          refreshTools();
        }}
      }} catch (e) {{}}
    }});

    async function refreshTools() {{
      try {{
        var res = await fetch(mountPath + "/docs/tools");
        var data = await res.json();
        if (data.tools) {{
          currentTools = data.tools;
          filterTools();
        }}
      }} catch (e) {{}}
    }}

    renderTools(currentTools);
  </script>
</body>
</html>"""
    return html
