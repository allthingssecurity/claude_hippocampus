#!/usr/bin/env bash
# CA3 associative memory activation hook
# Fires on UserPromptSubmit — passes stdin through to Python script
exec python3 /Users/I074560/Downloads/experiments/claude_nous/hooks/ca3-activation-hook.py
