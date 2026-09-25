---
title: wifi-doctor
emoji: 📶
colorFrom: indigo
colorTo: gray
sdk: gradio
sdk_version: 6.28.0
app_file: app.py
python_version: "3.12"
pinned: false
license: mit
short_description: LLM agent that diagnoses Wi-Fi failures from supplicant logs
---

# wifi-doctor

An LLM agent that reads a `wpa_supplicant` log and tells you why the Wi-Fi failed, and shows
you the exact lines it used as proof.

This Space runs the Gradio version of the demo (`app.py`). The primary live demo is on
Streamlit Community Cloud: <https://wifi-doctor.streamlit.app>. Source, evaluation results and
documentation: <https://github.com/iamgarvit/wifi-doctor>.

<!--
This file is uploaded as the Space's README.md by scripts/deploy_space.py; the YAML front
matter above is the Space's configuration. It is kept out of the GitHub README, where GitHub
would render it as a table.
-->
