# Sharingan setup runbook

Work in the project folder and preserve existing user files and `.env` values. Do not run paid inference during setup. No separate agent service is needed.

1. Detect OS, architecture, Python and package manager. Require Python 3.12+ and Rubber Band CLI. Use an existing compatible interpreter. macOS: install missing components with `brew install python@3.12 rubberband`. Ubuntu/Debian/WSL: `sudo apt install python3-venv rubberband-cli`. Native Windows: use Python 3.12 and an official Rubber Band binary on PATH, or WSL for Bash-based setup.
2. Create `.venv` and install `requirements.txt`. Windows: `py -3.12 -m venv .venv`, then `.venv\Scripts\python.exe -m pip install -r requirements.txt`. Bash: `bash setup.sh`.
3. For optional mesh modes use Python 3.12 and `bash setup-face-mesh.sh` in macOS/Linux/WSL. The isolated worker lives in `.venv-face`; its Google model downloads on first use. Fast mesh still needs Replicate for vocals.
4. Copy `.env.example` only if `.env` is absent. Have the user enter `SEEDANCE_API_KEY` (BytePlus ModelArk) and `REPLICATE_API_TOKEN` privately. Never request keys in chat, display values, or copy another project's secrets. ModelArk: https://ai.byteplus.com/ark/region:ap-southeast-1/apikey. Replicate: https://replicate.com/account/api-tokens. Seedance 2.5 model access and account balance are required. Preserve default API base/model unless the user has a compatible deployment.
5. Run `python -m unittest discover -s tests -v`, `python test_composite.py` and `python doctor.py --require-keys` through `.venv`. Use `doctor.py --mesh` when the optional worker is installed. These checks make no paid model calls.
6. Launch `python launch.py` through `.venv` in a persistent process/terminal. Bind to localhost. Default port 8770; if occupied, select a free port using `PORT`, without terminating unrelated processes. No callback or tunnel is required.
7. Verify `/health`, the UI, stylesheet, script and SVG. Check desktop/mobile layout and configuration status. Give the user the working localhost URL and report any missing dependencies/keys clearly.

Generation readiness requires Rubber Band, relevant worker dependencies, provider keys, enabled model access and balance. Offline doctor checks presence only, not paid provider access. A running UI alone does not establish generation readiness.
