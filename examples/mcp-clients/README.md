# Model Context Protocol (MCP) Client Integrations

Connect `cwv-speed-engine` directly into your AI coding assistant to give LLMs autonomous speed auditing, HTML transformation, and caching header tools.

---

## 🛠️ Setup Instructions by Client

### 1. Claude Desktop
Add to your Claude configuration file:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "cwv-speed-engine": {
      "command": "python3",
      "args": ["-m", "cwv_speed_engine.mcp_server"],
      "env": {
        "PYTHONPATH": "src"
      }
    }
  }
}
```

---

### 2. Cursor IDE
Add to `.cursor/mcp.json` or your global Cursor MCP settings:

```json
{
  "mcp": {
    "servers": {
      "cwv-speed-engine": {
        "command": "python3",
        "args": ["-m", "cwv_speed_engine.mcp_server"],
        "env": {
          "PYTHONPATH": "src"
        }
      }
    }
  }
}
```

---

### 3. Cline (VS Code Extension)
In Cline settings, edit your MCP Servers list and paste `cline_mcp.json`.

---

### 4. Zed Editor
Add to `~/.config/zed/settings.json`:

```json
{
  "context_servers": [
    {
      "id": "cwv-speed-engine",
      "command": {
        "path": "python3",
        "args": ["-m", "cwv_speed_engine.mcp_server"],
        "env": {
          "PYTHONPATH": "src"
        }
      }
    }
  ]
}
```
