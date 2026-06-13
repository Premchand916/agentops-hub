# README assets

Drop screenshots here so the main `README.md` renders them. Expected filenames:

| File | What to capture |
| ---- | --------------- |
| `cli-demo.png` | Terminal running `python app/cli.py` answering a VPN / PTO query with sources |
| `chainlit-ui.png` | Chainlit web UI (`chainlit run app/chainlit_app.py`) showing the routing step + answer |
| `langfuse-trace.png` | A Langfuse trace span for one `AgentHub.chat()` call (latency, routing, sources) |
| `eval-output.png` | Terminal output of `python evals/run_evals.py` (the category score table) |
| `a2a-agent-card.png` | Browser/curl hitting `/.well-known/agent.json` on the A2A server |

PNG at ~1400px wide looks best. Architecture/flow diagrams in the README are Mermaid — they render directly on GitHub, no image file needed.
