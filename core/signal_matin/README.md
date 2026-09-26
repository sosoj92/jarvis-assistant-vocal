# Module Signal Matin

Pipeline local et testable du journal A4 :

- `models.py` : schema Pydantic ;
- `sources.py` : adaptateurs Jarvis/RSS ;
- `normalizer.py` : validation et densite ;
- `renderer.py` : composants HTML ;
- `pdf.py` : Playwright vers PDF A4 ;
- `printer.py` : interface d'impression explicite ;
- `mock_data.py` : edition fictive complete ;
- `cli.py` : `generate`, `preview`, `print`, `data`.

Guide utilisateur : `docs/signal_matin.md`.
