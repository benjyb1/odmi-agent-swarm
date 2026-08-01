"""Prompts: versioned prompt browser."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.lib import db
from dashboard.lib.sidebar import page_header, render_session_widget


st.set_page_config(page_title="Prompts", page_icon="📝", layout="wide")
page_header("Prompts",
            "All versioned prompts. Editing happens in code; this page is read-only.")
render_session_widget()


prompts = db.prompt_versions()
if len(prompts) == 0:
    st.info("No prompts logged yet. Run any agent to register the first prompt.")
    st.stop()

# Summary
st.caption(f"{len(prompts)} prompt-version row(s).")

# Pick one to inspect.
prompts["label"] = prompts.apply(
    lambda r: f"#{r['id']}  {r['prompt_name']} v{r['version']}", axis=1,
)
picked = st.selectbox("Inspect prompt:", prompts["label"].tolist())
picked_id = int(picked.split()[0].lstrip("#"))
picked_row = prompts[prompts["id"] == picked_id].iloc[0]

with st.expander(f"Metadata for prompt #{picked_id}", expanded=False):
    st.json({
        "id": int(picked_row["id"]),
        "name": picked_row["prompt_name"],
        "version": int(picked_row["version"]),
        "description": picked_row.get("description"),
        "created_at": picked_row.get("created_at"),
    })

st.subheader("Prompt text")
text = db.prompt_text(picked_id)
if text:
    st.code(text, language="markdown")
else:
    st.warning("Prompt body not found.")
