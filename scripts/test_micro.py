"""Vumetre live + score du mot d'activation : sait-il que tu parles ?

    uv run python scripts/test_micro.py           # 20 secondes
    uv run python scripts/test_micro.py 40        # duree au choix

Quand Jarvis ne reagit pas a « Hey Jarvis », il n'y a que trois causes, et ce
script les distingue en une fois :

  1. aucun son n'arrive      -> barre plate : mauvais peripherique, ou
                                autorisation Microphone refusee au terminal
  2. du son arrive mais bas  -> barre qui bouge, score qui ne monte pas :
                                parle plus pres, ou baisse assistant.seuil_reveil
  3. tout va bien            -> le score depasse le seuil, DETECTE s'affiche

Rien n'est modifie : c'est un simple observateur.
"""
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from core import config, plateforme  # noqa: E402

TAUX = 16000
BLOC = 1280


def barre(niveau, largeur=40):
    """Vumetre texte, echelle racine pour rendre les faibles niveaux visibles."""
    rempli = min(largeur, int((niveau ** 0.5) * largeur * 2.2))
    return "#" * rempli + "." * (largeur - rempli)


def main():
    duree = 20.0
    for a in sys.argv[1:]:
        try:
            duree = float(a)
        except ValueError:
            pass

    print("=" * 62)
    print("  Test du micro et du mot d'activation")
    print("=" * 62)

    try:
        import numpy as np
        import sounddevice as sd
    except OSError as e:
        print(f"\n[X] PortAudio indisponible ({e}).")
        print("    brew install portaudio  puis  uv sync --reinstall-package sounddevice")
        return 1

    # ---- peripherique reellement utilise par Jarvis
    brut = config.reglage("audio.micro", plateforme.micro_defaut())
    micro = plateforme.peripherique_audio(brut)

    entrees = [(i, d["name"]) for i, d in enumerate(sd.query_devices())
               if d["max_input_channels"] > 0]
    if not entrees:
        print("\n[X] Aucune entree audio.")
        if plateforme.EST_MAC:
            print("    - Reglages Systeme > Confidentialite et securite > Microphone :")
            print("      coche ton terminal, puis RELANCE le terminal.")
            print("    - Mac mini / Mac Studio : aucun micro integre, branches-en un.")
        return 1

    print("\nEntrees disponibles :")
    for i, nom in entrees:
        print(f"  [{i}] {nom}")

    try:
        choisi = sd.query_devices(micro, "input") if micro is not None \
            else sd.query_devices(kind="input")
        print(f"\nJarvis ecoutera : {choisi['name']}")
    except Exception as e:
        print(f"\n[X] Le reglage audio.micro={brut!r} ne designe aucune entree ({e}).")
        print("    Mets un index de la liste ci-dessus, un nom, ou null.")
        return 1
    print(f"  (config audio.micro = {brut!r})")

    # ---- modele de mot d'activation, le meme que l'assistant
    seuil = float(config.reglage("assistant.seuil_reveil", 0.5))
    try:
        import openwakeword
        from openwakeword.model import Model as WakeModel
        modele = str(Path(openwakeword.__file__).parent / "resources" / "models"
                     / "hey_jarvis_v0.1.onnx")
        reveil = WakeModel(wakeword_model_paths=[modele])
    except Exception as e:
        print(f"\n[!] Mot d'activation indisponible ({e}) : vumetre seul.")
        reveil = None

    print(f"\nSeuil de declenchement : {seuil}")
    print(f"\nParle maintenant — dis « Hey Jarvis » plusieurs fois ({duree:.0f} s).\n")

    niveau_max, score_max, detections = 0.0, 0.0, 0
    fin = time.time() + duree
    with sd.InputStream(samplerate=TAUX, channels=1, dtype="float32",
                        device=micro, blocksize=BLOC) as flux:
        while time.time() < fin:
            bloc, _ = flux.read(BLOC)
            bloc = bloc.flatten()
            niveau = float(np.abs(bloc).max())
            niveau_max = max(niveau_max, niveau)

            score = 0.0
            if reveil is not None:
                scores = reveil.predict((bloc * 32767).astype(np.int16))
                score = float(max(scores.values()))
                score_max = max(score_max, score)
                if score >= seuil:
                    detections += 1
                    reveil.reset()

            marque = "  <<< DETECTE" if score >= seuil else ""
            print(f"\r  niveau {barre(niveau)} {niveau:5.3f}   "
                  f"mot-cle {score:4.2f}{marque}   ", end="", flush=True)

    # ---- verdict
    print("\n\n" + "=" * 62)
    print(f"  Niveau maximum : {niveau_max:.3f}")
    if reveil is not None:
        print(f"  Score maximum  : {score_max:.2f}  (seuil {seuil})")
        print(f"  Detections     : {detections}")
    print("=" * 62)

    if niveau_max < 0.01:
        print("\n[X] Aucun son n'arrive : le micro ne capte rien.")
        if plateforme.EST_MAC:
            print("    1. Autorisation Microphone du terminal, puis RELANCE-le.")
            print("    2. Mauvais peripherique : choisis un autre index ci-dessus")
            print("       et mets-le dans config.yaml (audio.micro).")
            print("    3. Micro coupe materiellement (bouton sur le casque).")
        return 1

    if detections:
        print("\n[OK] Le mot d'activation est reconnu. Jarvis doit repondre.")
        print("     S'il reste muet, c'est la SUITE qui bloque (cle API, LLM) :")
        print("     uv run python scripts/doctor.py")
        return 0

    print("\n[!] Le son arrive, mais « Hey Jarvis » n'a pas ete reconnu.")
    if niveau_max < 0.08:
        print(f"    Niveau faible ({niveau_max:.3f}) : rapproche-toi, monte le gain")
        print("    d'entree dans Reglages Systeme > Son > Entree.")
    print(f"    Score le plus haut atteint : {score_max:.2f} pour un seuil de {seuil}.")
    if score_max > 0.2:
        print("    Tu n'es pas loin : baisse le seuil dans config.yaml ->")
        print(f"      assistant:\n        seuil_reveil: {max(0.25, round(score_max - 0.1, 2))}")
    else:
        print("    Detache bien les deux mots : « HEY ... JARVIS », ton normal,")
        print("    a 30-50 cm du micro.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
