
import os
import sys
import time
import json
import shlex
import socket
import subprocess
from pathlib import Path
from urllib import request, error as urlerror
from prompts import generate_dockerfile, refine_dockerfile, test_verify

IMAGE = "my-vue"
CONTAINER = "my-vue"
PORT = 9528
READINESS_TIMEOUT_SEC = 120
READINESS_INTERVAL_SEC = 2

def log_section(title: str):
  print(f"\n=== {title} ===", flush=True)

def read_text(p: Path) -> str:
  try:
    return p.read_text(encoding="utf-8")
  except Exception:
    return None

def write_dockerfile_from_readme(readme_path: Path):
  log_section("Generating Dockerfile from README")
  if not readme_path.exists():
    raise RuntimeError(f"README not found: {readme_path}")
  project_root = readme_path.parent
  pkg = project_root / "package.json"
  if not pkg.exists():
    raise RuntimeError(f"package.json not found next to README: {pkg}")

  # Use LLM prompt to generate the Dockerfile based on README + specifications
  readme_text = read_text(readme_path) or ""
  # Provide the listing of the directory containing the README to the LLM
  try:
    folder_listing = "\n".join(
      sorted([f.name + ("/" if f.is_dir() else "") for f in project_root.iterdir()])
    )
  except Exception:
    folder_listing = ""
  specifications = (
    "Default command should start the vue dev server on port 9528\n"
  )
  dockerfile = generate_dockerfile(folder_listing, readme_text, specifications)

  out_path = project_root / "Dockerfile"
  out_path.write_text(dockerfile, encoding="utf-8")
  print(f"Dockerfile written to {out_path}")
  return project_root, out_path

def augmented_env():
  # Ensure Docker Desktop helper binaries are discoverable (fixes "docker-credential-desktop not found")
  env = os.environ.copy()
  candidates = [
    "/Applications/Docker.app/Contents/Resources/bin",
    "/Applications/Docker.app/Contents/MacOS",
    "/usr/local/bin",
    "/opt/homebrew/bin",
  ]
  path_sep = ";" if os.name == "nt" else ":"
  env["PATH"] = path_sep.join([env.get("PATH", "")] + candidates)
  # Enable BuildKit
  env["DOCKER_BUILDKIT"] = "1"
  return env

def run(cmd, cwd=None, env=None, live=False, check=False):
  if isinstance(cmd, str):
    cmd_list = shlex.split(cmd)
  else:
    cmd_list = cmd
  proc = subprocess.Popen(
    cmd_list,
    cwd=cwd,
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
  )
  stdout_chunks = []
  stderr_chunks = []
  while True:
    out = proc.stdout.readline()
    err = proc.stderr.readline()
    if out:
      stdout_chunks.append(out)
      if live:
        print(out, end="")
    if err:
      stderr_chunks.append(err)
      if live:
        print(err, end="", file=sys.stderr)
    if not out and not err and proc.poll() is not None:
      break
  stdout = "".join(stdout_chunks)
  stderr = "".join(stderr_chunks)
  if check and proc.returncode != 0:
    raise subprocess.CalledProcessError(proc.returncode, cmd_list, stdout, stderr)
  return proc.returncode, stdout, stderr

def ensure_docker():
  log_section("Checking Docker availability")
  code, out, err = run(["docker", "info"], env=augmented_env())
  if code == 0:
    print("Docker daemon is reachable.")
    return

  print("Docker not available, attempting to start Docker Desktop and wait for the daemon...")
  # macOS-specific
  run(["open", "-a", "Docker"])
  for i in range(READINESS_TIMEOUT_SEC // 2):
    code, _, _ = run(["docker", "info"], env=augmented_env())
    if code == 0:
      print("Docker daemon is reachable.")
      return
    time.sleep(2)

  # Final check
  code, _, err_final = run(["docker", "info"], env=augmented_env())
  if code != 0:
    print("Docker still not available. Details:\n" + (err_final or "").strip())
    raise RuntimeError("Docker is not available.")

def docker_build(project_root: Path):
  max_attempts = 10
  attempt = 1
  while True:
    log_section(f"Building Docker image (attempt {attempt}/{max_attempts})")
    # Forward common proxies as build args if present
    build_cmd = ["docker", "build", "-t", IMAGE]
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"]:
      if os.environ.get(key):
        build_cmd += ["--build-arg", f"{key}={os.environ[key]}"]
    build_cmd += ["."]
    code, out, err = run(build_cmd, cwd=str(project_root), env=augmented_env(), live=True)
    if code == 0:
      print(f"Image built: {IMAGE}")
      return

    # On failure, refine the Dockerfile using LLM with error messages
    msg = (err or "") + ("\n" + out if out else "")
    print("Docker build failed:\n" + msg)
    if "docker-credential-desktop" in msg:
      print("Hint: PATH fix applied for Docker Desktop helper binaries will be preserved across retries.")
    if "git ls-remote" in msg or "git://github.com" in msg or "Connection refused" in msg:
      print("Note: The Dockerfile generator/refiner can add RUN git config to rewrite git:// to https://.")

    if attempt >= max_attempts:
      raise RuntimeError("Build failed after maximum refinement attempts.")

    dockerfile_path = project_root / "Dockerfile"
    current_df = read_text(dockerfile_path) or ""
    try:
      refined = refine_dockerfile(current_df, msg)
    except Exception as e:
      print(f"Refine API failed: {e}. Will retry with the same Dockerfile next attempt.")
      attempt += 1
      continue

    if not refined or refined.strip() == current_df.strip():
      print("Refine produced no effective changes; aborting further refinement.")
      raise RuntimeError("Build failed and refinement produced no changes.")

    dockerfile_path.write_text(refined, encoding="utf-8")
    print("Refined Dockerfile written. Retrying build...")
    attempt += 1

def docker_rm(name: str):
  run(["docker", "rm", "-f", name], env=augmented_env())

def docker_run():
  log_section("Starting container")
  docker_rm(CONTAINER)
  code, out, err = run([
    "docker", "run", "-d",
    "--name", CONTAINER,
    "-p", f"{PORT}:{PORT}",
    IMAGE
  ], env=augmented_env(), live=True)
  if code != 0:
    raise RuntimeError("Failed to start container:\n" + (err or out))

  print(f"Container started: {CONTAINER}")

def http_ready(url: str, timeout_sec: int) -> bool:
  try:
    req = request.Request(url, method="GET")
    with request.urlopen(req, timeout=3) as resp:
      return 200 <= resp.status < 400
  except (urlerror.URLError, socket.timeout, ConnectionError):
    return False

def wait_for_ready(url: str, timeout_sec: int, interval_sec: int):
  log_section(f"Waiting for service to be ready at {url}")
  start = time.time()
  while time.time() - start < timeout_sec:
    if http_ready(url, 3):
      print("Service is responding.")
      return
    time.sleep(interval_sec)
  raise RuntimeError(f"Service not ready after {timeout_sec} seconds")

def docker_exec(cmd: str):
  log_section("Running tests inside the container")
  code, out, err = run(["docker", "exec", CONTAINER, "sh", "-lc", cmd], env=augmented_env(), live=True)
  return code, out, err

def docker_logs_tail(lines: int = 200) -> str:
  code, out, err = run(["docker", "logs", "--tail", str(lines), CONTAINER], env=augmented_env())
  return out or err or ""

def main():
  try:
    if len(sys.argv) < 2:
      print("Usage: python3 agent.py /path/to/vue-element-admin/README.md", file=sys.stderr)
      sys.exit(1)

    readme_arg = Path(sys.argv[1]).resolve()
    project_root, _ = write_dockerfile_from_readme(readme_arg)

    ensure_docker()

    max_test_attempts = 5
    for attempt in range(1, max_test_attempts + 1):
      log_section(f"Test attempt {attempt}/{max_test_attempts}")
      docker_build(project_root)
      docker_run()

      url = f"http://localhost:{PORT}/"
      try:
        wait_for_ready(url, READINESS_TIMEOUT_SEC, READINESS_INTERVAL_SEC)
        print(f"Service accessible at {url}")
      except Exception as e:
        print(f"WARNING: {e}")
        print("Collecting container logs for diagnostics:")
        print(docker_logs_tail(300))
        # Continue to tests even if readiness fails, per requirements.

      # Execute the specified test inside container
      test_cmd = "npx jest tests/unit/utils/validate.spec.js"
      code, out, err = docker_exec(test_cmd)
      combined_output = ""
      if out:
        combined_output += out
      if err:
        combined_output += ("\n" if combined_output else "") + err

      try:
        verdict = (test_verify(combined_output) or "").strip().lower()
      except Exception as ve:
        print(f"Verifier API failed: {ve}")
        verdict = "false"

      if verdict == "true":
        print("SUCCESS: All specified tests passed.")
        sys.exit(0)

      print("Tests judged as failed. Collecting diagnostics...")
      print(docker_logs_tail(400))
      if attempt < max_test_attempts:
        log_section("Regenerating Dockerfile from README and retrying")
        project_root, _ = write_dockerfile_from_readme(readme_arg)
        continue

      # No attempts left
      break

    sys.exit(2)

  except Exception as ex:
    print("\nFATAL ERROR:", str(ex), file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
  main()
