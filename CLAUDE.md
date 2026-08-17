# CLAUDE.md — CISStat TS Analysis

## Project
- Repository: C:\inetpub\CISStat\CISStat-TS-Analysis (branch: refactor/stage-1-architecture)
- Stack: Streamlit, Python
- Service: CISStat-TS-Analysis (NSSM, port 8501)

## Communication
- Communicate with user in Russian unless requested otherwise.
- Code, comments, identifiers — English.
- User-facing strings: English in code; localized only in dedicated locale files.

## Engineering Principles (priority order)
1. Correctness
2. Safety
3. Repository consistency
4. Maintainability
5. Performance
6. Cost
7. Response speed

When principles conflict, higher priorities win.

## Change Minimization
- Prefer the smallest valid change.
- Avoid large rewrites.
- Avoid new abstractions unless justified.

## Repository Preservation
Never change without explicit request:
- public API
- module names
- directory structure
- build system

## Architecture Changes
Require explicit user confirmation:
- new layer
- new dependency
- new module
- public API change

## Safety Rules
Never auto-approve changes involving:
- secrets / credentials
- authentication / authorization
- cryptography
- migrations
- destructive SQL
- shell execution
- infrastructure / deployment
- production configuration

## Behavior
- Do not generate full code blocks unless explicitly required.
- Prefer: a precise step-by-step plan, a minimal verified diff, or an explicit request for confirmation.
- Always explain the decision and trade-offs in 1-2 sentences.

## Models (native tier routing)
- Tier routing is handled natively by Claude Code through the admin proxy at http://127.0.0.1:6419
- Opus  -> Qwen3.6-27B-MTP     (deep reasoning, complex tasks)
- Sonnet -> Qwen3.6-35B-A3B-MTP (standard coding tasks)
- Haiku  -> Qwen3.6-35B-A3B-MTP (trivial tasks, file search)
- No manual delegation or MCP layer is used.

## Communication

- Communicate with user in Russian.
- Code, comments, identifiers — English.
