# Automated Docker Builder & Tester Agent

This repository is a Python-based agent that uses an LLM to:
- Generate and refine a Dockerfile from a project README.
- Build a Docker image (name auto-derived from the project folder) and run a container exposing an auto-detected port (from Dockerfile EXPOSE/README/package.json/.env; fallback 9528).
- Run tests inside the container (auto-detected test command, e.g., npm run test:unit, npx jest tests/unit, npx vitest run).
- Iteratively refine the Dockerfile using build/test logs until success or attempts are exhausted.

The agent is configured to work with the included `vue-element-admin/` project (PanJiaChen/vue-element-admin) and focuses on verifying its unit tests for `utils/validate`.

See: `Coding Task - Agent.pdf` for the original task description and success criteria.

---

## Contents

- Overview
- Architecture
- Prerequisites
- Setup
- Usage
- Providing Specifications
- What the agent does
- Configuration (AI backends, env vars)
- Troubleshooting
- Security notes
- Repository structure
- License and credits

---

## Overview

Given a path to a repository README, the agent:
1. Calls an LLM to produce a Dockerfile tailored to the project and provided specs.
2. Builds a Docker image (auto-derived name), runs it as a container, and maps the auto-detected port (fallback 9528).
3. Waits for readiness and runs the auto-detected test command inside the container (e.g., npm run test:unit, npx jest tests/unit, npx vitest run).
4. If the build/test fails, the agent:
   - Collects logs and error output.
   - Uses the LLM to refine the Dockerfile.
   - Retries build/run/tests up to configured attempt limits.

Success criteria (from the task):
- The project is accessible at http://localhost:9528/
- All tests pass for `tests/unit/utils/validate.spec.js`

---

## Architecture

Key modules:
- `agent.py`
  - CLI entry; orchestrates Dockerfile generation, build, run, readiness checks, test execution, and iterative refinement.
- `prompts.py`
  - Contains prompt templates and wrapper functions to interact with the LLM for:
    - Initial Dockerfile generation
    - Refinement using error logs
    - Verifying whether tests passed (LLM-based judge)
- `ai_interface.py`
  - Lazy-loads the selected model backend (OpenAI, Anthropic/Claude, Ollama, etc.).
- `models.py`
  - Concrete model client wrappers:
    - `OpenAIModel` (OpenAI Python SDK)
    - `ClaudeModel` (Anthropic Python SDK)
    - `OllamaModel` (Local Ollama)
  - Returns a unified `response_body` for downstream use.

Runtime behavior highlights:
- Image/container name: auto-derived from project folder name (slug)
- Port detection: auto-detected from Dockerfile EXPOSE/README/package.json/.env; fallback 9528
- Test command detection: auto-detected from package.json scripts or dependencies (jest/vitest); fallback "npm test --silent"
- Readiness wait: up to 120s (polling every 2s).
- Build retries with refinement: up to 10 attempts per build cycle.
- Test cycles: up to 5 attempts. On each failed attempt, the agent can regenerate/refine the Dockerfile and retry.

Platform note:
- `ensure_docker()` attempts to start Docker Desktop on macOS via `open -a Docker` if the daemon is not reachable. On Linux/Windows, ensure the Docker daemon is running beforehand.

---

## Prerequisites

- Python 3.9+ (tested with 3.10+ recommended)
- Docker installed and running
  - macOS: Docker Desktop
  - Linux/Windows: Docker daemon
- Network access for base images/dependencies during `docker build`

Optional (for your selected AI backend):
- OpenAI
  - Environment: `OPENAI_API_KEY`
  - Python package: `openai`
- Anthropic (Claude)
  - Environment: `ANTHROPIC_API_KEY`
  - Python package: `anthropic`
- Ollama (local)
  - Ollama running locally
  - Python package: `ollama`

---

## Setup

Create a virtual environment and install dependencies:
```bash
python3 -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate
pip install -U pip

# Install only what you need for your chosen backend; OpenAI is default in code.
pip install openai anthropic ollama
```

Environment variables (as needed):
```bash
# OpenAI (default backend used by code)
export OPENAI_API_KEY="sk-..."

# Anthropic (Claude)
export ANTHROPIC_API_KEY="sk-ant-..."

# If your environment uses proxies and you want Docker to see them during build:
export HTTP_PROXY="http://proxy:port"
export HTTPS_PROXY="http://proxy:port"
export NO_PROXY="localhost,127.0.0.1"
```

---

## Usage

Run the agent by passing the README file of the target project:
```bash
python3 agent.py vue-element-admin/README.md
```

What happens:
- The agent generates `vue-element-admin/Dockerfile` via LLM.
- Builds an image (auto-derived name) and starts a container mapping `<port>:<port>` where the port is auto-detected (fallback 9528).
- Waits for readiness and then runs the auto-detected test command inside the container (examples: npm run test:unit, npx jest tests/unit, npx vitest run).
- Interprets the test output via an LLM judge to determine pass/fail.
- If it fails, it will collect logs and retry with refined Dockerfiles up to the configured limits.

On success, you will see:
```
SUCCESS: All specified tests passed.
```

To manually inspect the app (if the dev server is running in the container), visit:
- http://localhost:<detected-port>/ (defaults to 9528 if not found)

---

## Providing Specifications

You can provide custom specifications that guide the LLM when generating the Dockerfile. These specs are combined with the target README and folder listing.

Supported sources (highest precedence first):
1. Inline flag: --spec "..." or -s "..."
2. From file: --spec-file PATH or -f PATH
3. Environment variables: DOCKER_SPECS, DOCKER_SPECIFICATIONS, or SPECIFICATIONS
4. Second positional argument after the README path (must not start with "-")
5. Fallback default: Default command should start the vue dev server on port 9528

Examples:
```bash
# Positional specs
python3 agent.py vue-element-admin/README.md "Use Node 18, install with yarn, expose 9528, run npm run dev"

# Inline flag
python3 agent.py vue-element-admin/README.md --spec "Use Node 18, install with yarn, expose 9528, run npm run dev"

# From file
python3 agent.py vue-element-admin/README.md --spec-file ./specs.txt

# From environment variable
export DOCKER_SPECS="Use Node 18, install with yarn, expose 9528, run npm run dev"
python3 agent.py vue-element-admin/README.md
```

Precedence:
--spec/--spec-file > environment variables > second positional argument > default.

## What the agent does (detailed)

1. Generate Dockerfile (`prompts.generate_dockerfile`)
   - Input: README content + folder listing + specs (e.g., “Default command should start the vue dev server on port 9528”).
   - Output: A complete Dockerfile written next to the README.
   - Retries (re-generate/refine) up to 5 attempts.

2. Build with Docker
   - Target image: auto-derived name.
   - Forwards proxy-related env vars (`HTTP_PROXY`, etc.) to the build.
   - On failure, dump logs and call `prompts.refine_dockerfile` with error messages.

3. Run container
   - Name: auto-derived
   - Port mapping: `-p <port>:<port>` (auto-detected; fallback 9528)

4. Readiness
   - Polls `http://localhost:9528/` for up to 120s.
   - If not ready, it will still proceed to tests and print diagnostics.

5. Tests
   - Executes inside the container: auto-detected test command (examples: npm run test:unit, npx jest tests/unit, npx vitest run)
   - Uses `prompts.test_verify` to robustly judge pass/fail from output.
   - Retries (re-generate/refine) up to 5 attempts.

---

## Configuration

- Image/container name and port
  - Image/container: auto-derived from project folder (slug)
  - Port: auto-detected from Dockerfile EXPOSE/README/package.json/.env; fallback 9528
  - Test command: auto-detected from package.json scripts or dependencies (jest/vitest); fallback "npm test --silent"
  - You can influence Dockerfile CMD/EXPOSE via "Providing Specifications" or by editing the generated Dockerfile.

- Attempt limits and timings
  - `READINESS_TIMEOUT_SEC = 120`
  - `READINESS_INTERVAL_SEC = 2`
  - Build refinements: up to 10 per cycle
  - Test cycles: up to 5 (`max_test_attempts`)

- AI backend and model
  - The default constructor in `prompts.py` uses `AIInterface()` with defaults (`backend="openai"`, `model="gpt-5-mini-2025-08-07"` placeholder).
  - To change backend/model, update `prompts.py` to pass explicit values:
    ```python
    # Example: use Claude
    ai = AIInterface(backend="claude", model="claude-3-5-sonnet-20240620")

    # Example: use OpenAI with a current model
    ai = AIInterface(backend="openai", model="gpt-4o-mini")  # or "o3-mini"
    ```
  - Implementations currently provided in `models.py`:
    - `OpenAIModel`, `ClaudeModel`, `OllamaModel`
  - `ai_interface.py` lists backends for Gemini and Together, but corresponding model classes are not implemented in `models.py`. Add them if needed.

---

## Troubleshooting

- Docker not reachable
  - Ensure Docker Desktop (macOS) or Docker daemon is running.
  - The agent tries `open -a Docker` on macOS if the daemon is not ready.

- Build fails repeatedly
  - The agent prints full build logs and refines the Dockerfile between attempts.
  - Common issues:
    - Network/proxy errors during `npm install` or `git` fetch
    - Node/Yarn/PNPM tooling mismatches
  - The refiner may add lines like:
    - `RUN git config --global url."https://".insteadOf git://`
    - Proxy environment usage
  - You can inspect the evolving `Dockerfile` under `vue-element-admin/`.

- Container starts but http://localhost:9528/ is not ready
  - The agent still runs tests; readiness is best-effort.
  - Check docker logs printed by the agent (it prints the container name).

- Test verification seems incorrect
  - `prompts.test_verify` uses an LLM judge. You can also manually inspect the Jest output printed before the judge’s verdict.
  - To reduce ambiguity, prefer deterministic test outputs and keep logs concise.

- API/SDK errors
  - Ensure the right Python packages are installed (openai/anthropic/ollama).
  - Ensure required API keys are exported (e.g., `OPENAI_API_KEY`).
  - For OpenAI o1/o3 models, the request formatting in `models.py` adapts automatically.

---

## Security notes

- The agent builds and runs a Dockerfile produced by an LLM based on the README and logs. Review generated Dockerfiles if you have strict security requirements.
- Prefer running in a controlled environment/network with restricted credentials.
- Do not pass secrets into container builds unless absolutely necessary.

---

## Repository structure

Top-level (abridged):
```
.
├── agent.py
├── ai_interface.py
├── models.py
├── prompts.py
├── Coding Task - Agent.pdf
├── vue-element-admin/                # upstream project copy
│   ├── package.json
│   ├── src/ ...
│   ├── tests/unit/utils/validate.spec.js
│   └── README.md (input to the agent)
└── README.md (this file)
```

---

## Future Plans & Collaboration

If you’re interested in this project, and want to empower AI to real-world software engineering tasks, I’m open to collaboration.

My future goals are:
1. Support for different project build tools (e.g., Cargo, Maven, CMake)
2. Automated vulnerability scanning
3. Using RAG (Retrieval-Augmented Generation) to retrieve environment variables required for project builds

## License and credits

- The `vue-element-admin` project is by PanJiaChen and is distributed under its own license. See `vue-element-admin/LICENSE` for details.
- This agent code is provided as-is for automating Docker build/refinement/testing of the included repo as part of the described task.
