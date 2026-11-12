"""Load standalone overrides and shared workspace model configuration."""

from pathlib import Path

from dotenv import load_dotenv


def load_model_environment():
    """Process environment wins, then compiler .env, then workspace .env."""
    compiler = Path(__file__).resolve().parents[3]
    load_dotenv(compiler / ".env", encoding="utf-8-sig", override=False)
    for parent in compiler.parents:
        if (parent / "config.toml").is_file() and (parent / "pipeline").is_dir():
            load_dotenv(parent / ".env", encoding="utf-8-sig", override=False)
            break


def endpoint_model_name(name):
    """Accept shared provider selectors while preserving other model namespaces."""
    return name.removeprefix("openai/").removeprefix("openai:").removeprefix("deepseek/")
