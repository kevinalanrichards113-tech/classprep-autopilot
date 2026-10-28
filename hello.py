#!/usr/bin/env python3
"""Day 1 gate test: one hello-world call to the Meta Model API.

Usage:  python3 hello.py
Reads MODEL_API_KEY from the environment or from .env in this folder.
On success, prints the model that answered so it can be recorded in README.
"""
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import meta_api

if __name__ == "__main__":
    print(f"Endpoint: {meta_api.BASE_URL}  Model: {meta_api.get_model()}")
    try:
        out = meta_api.chat(
            "You are Muse Spark, answering a connectivity test.",
            "Say hello in one short sentence and confirm which model you are.",
            max_output_tokens=2000,
        )
    except RuntimeError as e:
        print(f"FAILED: {e}")
        sys.exit(1)
    print("API answered:")
    print(out)
    print("GATE PASSED — record this model + endpoint in README.md")
