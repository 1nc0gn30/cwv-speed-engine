# Model Context Protocol (MCP) Guide for `cwv-speed-engine`

The Model Context Protocol (MCP) connects AI models (Claude, Cursor, Cline, Zed, Devin) directly to development tooling. `cwv-speed-engine` includes a native, zero-dependency MCP server that gives AI coding assistants autonomous capabilities to audit, optimize, and verify Core Web Vitals performance.

---

## 🚀 Available MCP Tools

### 1. `audit_url`
Audits a live web page, measures TTFB, analyzes DOM structure, and returns a detailed Core Web Vitals score breakdown.

```json
{
  "name": "audit_url",
  "description": "Performs comprehensive Core Web Vitals audit on a live URL.",
  "parameters": {
    "type": "object",
    "properties": {
      "url": { "type": "string", "description": "The URL to audit" },
      "device": { "type": "string", "enum": ["mobile", "desktop"], "default": "mobile" }
    },
    "required": ["url"]
  }
}
```

---

### 2. `audit_html`
Audits raw HTML markup for layout shifts, missing image dimensions, FOIT font risks, and render-blocking scripts.

```json
{
  "name": "audit_html",
  "description": "Audits raw HTML content for LCP, CLS, INP, FCP, and TTFB bottlenecks.",
  "parameters": {
    "type": "object",
    "properties": {
      "html": { "type": "string", "description": "HTML source code to analyze" },
      "device": { "type": "string", "enum": ["mobile", "desktop"], "default": "mobile" }
    },
    "required": ["html"]
  }
}
```

---

### 3. `transform_html`
Applies automated AST speed optimizations to raw HTML markup.

```json
{
  "name": "transform_html",
  "description": "Automated speed optimization of HTML markup.",
  "parameters": {
    "type": "object",
    "properties": {
      "html": { "type": "string", "description": "Raw HTML markup" },
      "options": {
        "type": "object",
        "properties": {
          "dimensions": { "type": "boolean", "default": true },
          "lazy_loading": { "type": "boolean", "default": true },
          "font_preconnect": { "type": "boolean", "default": true },
          "defer_scripts": { "type": "boolean", "default": true },
          "preload_hero": { "type": "boolean", "default": true }
        }
      }
    },
    "required": ["html"]
  }
}
```

---

### 4. `generate_pwa`
Generates a complete Progressive Web App suite (`site.webmanifest`, `sw.js`, `offline.html`).

```json
{
  "name": "generate_pwa",
  "description": "Generates PWA manifest, service worker caching code, and offline fallback.",
  "parameters": {
    "type": "object",
    "properties": {
      "name": { "type": "string", "default": "My Speed App" },
      "short_name": { "type": "string", "default": "SpeedApp" },
      "theme_color": { "type": "string", "default": "#1a73e8" },
      "strategy": {
        "type": "string",
        "enum": ["stale-while-revalidate", "cache-first", "network-first"],
        "default": "stale-while-revalidate"
      }
    }
  }
}
```

---

### 5. `generate_cache_headers`
Generates optimized caching configuration files for Netlify, Vercel, Nginx, Cloudflare, Apache, or Next.js.

```json
{
  "name": "generate_cache_headers",
  "description": "Generates optimized Cache-Control headers.",
  "parameters": {
    "type": "object",
    "properties": {
      "platform": {
        "type": "string",
        "enum": ["netlify", "vercel", "nginx", "cloudflare", "apache", "nextjs"]
      }
    },
    "required": ["platform"]
  }
}
```

---

### 6. `compare_performance`
Compares baseline vs candidate performance diff to measure improvement deltas.

```json
{
  "name": "compare_performance",
  "description": "Compares baseline vs candidate performance diff and calculates score improvement.",
  "parameters": {
    "type": "object",
    "properties": {
      "baseline_html": { "type": "string" },
      "candidate_html": { "type": "string" }
    },
    "required": ["baseline_html", "candidate_html"]
  }
}
```

---

## 🔧 Client Configuration Guide

### Claude Desktop
File: `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

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

### Cursor IDE
File: `.cursor/mcp.json`

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
