"""Prompt templates and builders for every agent.

Each module exports three things:

- NAME (str): the prompt_versions.prompt_name value.
- VERSION (int): the prompt_versions.version value. Bump on iteration.
- a build_*_message() function that takes the agent's typed input and
  returns the user message string to send.

The system prompt is exported as a constant. The LLM wrapper appends
the JSON schema of the expected output to the system prompt.
"""
