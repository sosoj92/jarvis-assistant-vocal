"""Test rapide de l'agenda, sans la voix : affiche ce que get_events repondrait.

Lance-le avec :  uv run python tester_agenda.py
La 1re fois, une page web s'ouvre pour autoriser l'acces (cree google_token.json).
"""
from core import registre
registre.charger_outils()
from tools.agenda import get_events, _service

print("Connexion a Google Agenda...")
try:
    # Diagnostic manuel : l'autorisation peut s'ouvrir meme sur un poste
    # configure en serveur sans peripheriques.
    svc = _service(interactif=True)
    cals = svc.calendarList().list().execute().get("items", [])
    print(f"OK — {len(cals)} agenda(s) accessibles :",
          ", ".join(c.get("summary", "") for c in cals))
except Exception as e:
    print("Echec de connexion :", e)
    print("-> Verifie google_credentials.json a la racine (voir docs/agenda.md).")
    raise SystemExit(1)

for periode in ["aujourd'hui", "demain", "cette semaine"]:
    print(f"\n=== {periode} ===")
    print(get_events(periode))
