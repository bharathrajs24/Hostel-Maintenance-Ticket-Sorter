# Hostel Care Web App

## Run on Windows
1. Extract the ZIP.
2. Open the `hostel_ticket_sorter` folder in VS Code.
3. In Terminal run:
   ```powershell
   python -m pip install -r requirements-web.txt
   python -m streamlit run app.py
   ```
4. Open the local URL printed by Streamlit (usually http://localhost:8501).

The web UI uses the original `ticket_sorter.py`, `rules.py`, and `llm_client.py` logic. By default, complaint sorting uses the project's offline mock classifier. To use a real LLM, configure `.env` using `.env.example` and select a supported provider.
