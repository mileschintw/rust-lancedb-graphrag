#!/usr/bin/env bash
ls -la "$HOME/.local/bin/uv" 2>&1 | head -2; "$HOME/.local/bin/uv" --version 2>&1 | head -1
bash -lc 'command -v uv; echo "login PATH=$PATH"' 2>&1 | head -3
