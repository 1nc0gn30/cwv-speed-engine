# ⚡ Google Speed Studio & Core Web Vitals Engine (`cwv-speed-engine`)

[![CI Matrix](https://github.com/google/cwv-speed-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/google/cwv-speed-engine/actions/workflows/ci.yml)
[![Python Versions](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://pypi.org/project/cwv-speed-engine/)
[![UI](https://img.shields.io/badge/UI-Google%20Material%203-4285F4)](https://github.com/google/cwv-speed-engine)
[![MCP Ready](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-9334e6)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](./LICENSE)

**Google Speed Studio** (`cwv-speed-engine`) is an enterprise-grade Core Web Vitals auditing, automated speed transformation, PWA generation, and AI Agent MCP hub designed to help modern web applications achieve and maintain a perfect **100/100 Core Web Vitals score** (LCP < 1.2s, CLS 0, INP < 50ms).

---

## 🌟 Key Capabilities

- 🎨 **Google Material 3 Speed Studio Web UI**: Full-featured, offline-ready web UI with animated Speed Gauge Dial, metric cards, and 8 interactive studios.
- ⚡ **Deterministic Core Web Vitals Auditor**: In-depth standards-based analysis for LCP, CLS, INP, FCP, and TTFB with actionable remediation advice.
- 🛠️ **Automated HTML Speed Transformer**: Automated AST rewrites that inject explicit image dimensions, native lazy loading, font preconnects, script deferrals, and hero preload priority tags.
- 📱 **PWA & Service Worker Studio**: Interactive builder for W3C web manifests and tiered Service Worker caching strategies (`stale-while-revalidate`, `cache-first`, `network-first`).
- 🖼️ **OpenGraph & Social Previewer**: Live mockups for Google Search SERP, Twitter Cards, and LinkedIn snippets with 1-click meta tag copying.
- ⚖️ **Performance Diff Comparator**: Measure before vs after speed gains, metric deltas, and resolved audit findings.
- 🚀 **Cache-Control & Headers Exporter**: Instant production configs for Netlify, Vercel, Nginx, Cloudflare, Apache, and Next.js.
- 🤖 **AI Agent & MCP Hub**: Zero-dependency Model Context Protocol (MCP) server supporting Claude Desktop, Cursor, Cline, and Zed.
- 🚦 **CI/CD Quality Gate**: Reusable GitHub Actions workflow to block PRs regressing speed scores.
- 📦 **Zero Mandatory Dependencies**: Core engine and web server run purely on the Python standard library.

---

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/google/cwv-speed-engine.git
cd cwv-speed-engine

# Install in editable mode
pip install -e .
```

### Launch Google Speed Studio Web UI

```bash
python -m cwv_speed_engine.ui_server --port 8448 --open
```

Open your browser to [http://localhost:8448](http://localhost:8448) to access the interactive studio.

---

## 💻 CLI Commands Cheatsheet

```bash
# 1. Audit a live URL
cwv-speed audit https://example.com --device mobile

# 2. Audit raw HTML markup
cwv-speed audit --html "<!DOCTYPE html>..."

# 3. Automatically transform HTML for maximum speed
cwv-speed optimize unoptimized.html -o index.html

# 4. Generate Progressive Web App Suite
cwv-speed pwa --name "My Speed App" --strategy stale-while-revalidate

# 5. Export Production Cache Headers
cwv-speed cache --platform netlify -o _headers

# 6. Run CI Gate on Pull Requests
cwv-speed ci-gate https://staging.example.com --min-score 90 --max-cls 0.05
```

---

## 🤖 AI Agent MCP Integration (Claude & Cursor)

`cwv-speed-engine` runs natively as an MCP server over stdio.

### Claude Desktop Setup
Add to `claude_desktop_config.json`:

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

### Cursor IDE Setup
Add to `.cursor/mcp.json`:

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

## 📂 Production Reference Examples

Explore production architecture blueprints in [`examples/`](./examples/):
- [`examples/nextjs-optimized/`](./examples/nextjs-optimized/): Next.js 14/15 App Router image optimization, font self-hosting, Early Hints edge middleware.
- [`examples/astro-speed/`](./examples/astro-speed/): Astro zero-JS Island architecture, `<SpeedHead />` component, sharp image processing.
- [`examples/pwa-manifest/`](./examples/pwa-manifest/): W3C PWA manifest, tiered `sw.js` caching, Material 3 offline page.
- [`examples/nginx-caching/`](./examples/nginx-caching/): Nginx configuration for sub-50ms TTFB and 1-year immutable caching.
- [`examples/mcp-clients/`](./examples/mcp-clients/): Ready-to-copy client configs for Claude, Cursor, Cline, and Zed.

---

## 📚 Documentation

- [Core Web Vitals Metric Guide (2024-2026 Standards)](./docs/CORE_WEB_VITALS_GUIDE.md)
- [Model Context Protocol (MCP) Guide](./docs/MCP_GUIDE.md)
- [High-Performance Caching & HTTP Headers Guide](./docs/CACHING_STRATEGIES.md)

---

## 🧪 Running Tests

```bash
PYTHONPATH=src pytest tests/ -v
```

---

## 📄 License

Apache License 2.0. See [LICENSE](./LICENSE) for details.
