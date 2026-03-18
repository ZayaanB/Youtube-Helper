# Contributing to YouTube Helper

## Setup

1. Clone the repo and create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and add your OpenRouter API key.

4. On Linux, install `python3-tk` for the GUI:

```bash
sudo apt install python3-tk
```

## Running

- GUI: `python app.py`
- CLI: `python app.py --cli`
- Verbose: `python app.py --verbose` or `python app.py --cli -v`

## Code style

- Use type hints for function signatures.
- Keep comments short. Add them where they explain something non-obvious.
- Run `ruff check .` and `ruff format .` if you have ruff installed.
