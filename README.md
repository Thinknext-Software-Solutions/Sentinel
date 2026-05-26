# Sentinel

> Point it at a URL. It explores the app, generates a test plan, runs it, and reports findings. Web + visual regression + accessibility in v0.1; API + mobile in later versions.

[![PyPI](https://img.shields.io/pypi/v/sentinel-agent.svg?label=PyPI&color=22d3ee)](https://pypi.org/project/sentinel-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Status](https://img.shields.io/badge/status-alpha-22d3ee.svg)](#roadmap)
[![Built by ThinkNext](https://img.shields.io/badge/built%20by-ThinkNext-22d3ee.svg)](https://thinknextsoftware.com)

> **Status**: alpha, live on PyPI as `sentinel-agent==0.1.0a1`. Web + visual regression + accessibility ship today. API testing in v0.1.0a2; mobile (React Native) in v0.1.0a3.
>
> **Install**: `pip install sentinel-agent` &middot; **Repo**: [GitHub](https://github.com/Thinknext-Software-Solutions/Sentinel) &middot; **Issues**: [file one](https://github.com/Thinknext-Software-Solutions/Sentinel/issues)

## What it does

Point Sentinel at a URL:

```bash
sentinel run https://your-app.com
```

In one command, the agent:

1. **Opens** the URL in headless Chromium
2. **Reads** the rendered HTML + visible text
3. **Asks the LLM** to generate a focused test plan (2-5 scenarios, 3-8 steps each)
4. **Runs** the plan in fresh browser sessions per scenario
5. **Captures** screenshots and compares against baselines (visual regression)
6. **Scans** each page state for WCAG 2.1 AA violations (axe-core)
7. **Reports** findings: failed scenarios, visual diffs, accessibility issues, with cost

## Why this exists

The same teams that need [Cascade](https://cascadeagent.dev) (meeting-to-PR) and [Relay](https://github.com/Thinknext-Software-Solutions/Relay) (issue-to-PR) need a way to verify that the PRs those agents produce actually work. Hand-writing Playwright tests for every feature is the bottleneck. Sentinel removes the bottleneck: generate tests with the same LLM that writes the code.

Sentinel sits next to Cascade and Relay as the third ThinkNext open-source product. Shared internals (LLM clients, error types) come from `cascade-agent`.

## Install

```bash
pip install sentinel-agent

# One-time: install the Chromium binary Playwright needs
playwright install chromium
```

## Configure

```bash
# Reuses cascade-agent's credentials; configure once for all three products
cascade configure llm anthropic --key sk-ant-xxx --set-default
```

If you want a project-local config (highly recommended; lets you set viewport, baseline directory, accessibility thresholds):

```bash
sentinel init
```

This scaffolds `sentinel.yaml` with sensible defaults you can edit.

## Run

```bash
sentinel run https://cascadeagent.dev

# Output (truncated):
#   ✓  3/3 scenarios passed, 0 visual diff(s), 2 a11y violation(s)
#
#   ✓  Homepage loads and primary CTA is visible  (1.42s)
#   ✓  Get-started link navigates to /getting-started/  (1.83s)
#   ✓  Docs sidebar contains all expected sections  (2.10s)
#
#   Accessibility violations:
#     [moderate] color-contrast: Elements must meet minimum color contrast...
#       sample: .text-slate-500
#       (3 node(s) affected)
#     [minor] image-alt: Images must have alt text...
#       sample: img.hero-illustration
#       (1 node(s) affected)
#
#   cost:    $0.04 (5,210 in / 980 out tokens)
```

## What ships in v0.1.0a1

| Capability | Status | Module |
|---|---|---|
| Web testing via Playwright | ✅ | `sentinel.browser`, `sentinel.runner` |
| LLM-driven test plan generation | ✅ | `sentinel.planner` |
| Visual regression (PIL pixel diff) | ✅ | `sentinel.visual` |
| Accessibility scan (axe-core 4.10) | ✅ | `sentinel.a11y` |
| Multi-page exploration | 🚧 v0.1.0a2 | (plans are single-URL today) |
| API contract testing (OpenAPI) | 🚧 v0.1.0a2 | |
| Self-healing tests (re-plan on failure) | 🚧 v0.1.0a2 | |
| Mobile (React Native via Detox) | 🚧 v0.1.0a3 | |

## How it differs from existing tools

| | Playwright Codegen | Pytest + Playwright | Percy / Chromatic | Sentinel |
|---|---|---|---|---|
| Generates tests from a URL | partial (record/replay) | ❌ | ❌ | ✅ |
| Self-hosted | ✅ | ✅ | ❌ | ✅ |
| Bring your own LLM | n/a | n/a | n/a | ✅ |
| Visual regression | ❌ | ❌ | ✅ | ✅ |
| Accessibility scan | ❌ | partial (plugin) | ❌ | ✅ |
| Open source | ✅ | ✅ | ❌ | ✅ |

Sentinel is for teams who want test coverage without spending the engineering hours to author it. The trade-off is that AI-generated tests have failure modes hand-written tests do not (e.g. an LLM picks a fragile selector). The self-healing v0.1.0a2 feature is the answer to that.

## Configuration

`sentinel.yaml` (after `sentinel init`):

```yaml
version: 1

agent:
  provider: anthropic
  model: claude-opus-4-7
  temperature: 0.2

browser:
  headless: true
  viewport_width: 1280
  viewport_height: 720
  timeout_ms: 30000

visual:
  enabled: true
  baseline_dir: sentinel-baselines
  diff_threshold_percent: 0.5

a11y:
  enabled: true
  fail_on:
    - critical
    - serious
```

## Architecture

```
   sentinel run <url>
          │
          ▼
   ┌──────────────┐
   │ explore page │  Playwright opens URL, grabs HTML + visible text
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │   planner    │  LLM produces TestPlan (2-5 scenarios, 3-8 steps each)
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │    runner    │  Fresh browser session per scenario
   │              │  Each step is one Playwright action
   │              │  screenshot steps → visual regression check
   │              │  a11y_scan steps → axe-core injection
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ SentinelReport │  Scenarios + visual diffs + a11y violations + cost
   └──────────────┘
```

## Roadmap

| Version | Status | Highlights |
|---|---|---|
| **v0.1.0a1** | Shipped (2026-05-26) | Web testing, visual regression, accessibility |
| v0.1.0a2 | Planned | Multi-page exploration, self-healing tests, API contract testing |
| v0.1.0a3 | Planned | Mobile (React Native via Detox or Maestro) |
| v0.2 | Q4 2026 | CI integration (GitHub Actions / GitLab CI / Bitbucket / Azure), parallel execution |
| v1.0 | Mid-2027 | Stable API, full coverage of web + API + mobile + visual + a11y, baselined |

## License

MIT. See [LICENSE](LICENSE).

## About

Built and maintained by [ThinkNext Software Solutions](https://thinknextsoftware.com), alongside our other open-source projects [Cascade](https://cascadeagent.dev) (meeting-to-PR) and [Relay](https://github.com/Thinknext-Software-Solutions/Relay) (issue-to-PR).

Follow along: [@ThinkNextHQ](https://twitter.com/ThinkNextHQ) &middot; [LinkedIn](https://linkedin.com/company/thinknextsoftware) &middot; [Blog](https://thinknextsoftware.com/blog/)
