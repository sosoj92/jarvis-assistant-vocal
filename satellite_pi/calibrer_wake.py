#!/usr/bin/env python3
"""Mesure le score openWakeWord sans conserver l'audio capture."""

import argparse
import time
from math import gcd
from pathlib import Path

import numpy as np
import openwakeword
import sounddevice as sd
import yaml
from openwakeword.model import Model
from scipy.signal import resample_poly

# Meme choix de micro que le satellite (nom, index ou liste de noms par ordre de
# preference) : la calibration mesure le micro que le satellite ouvrira.
from jarvis_satellite import _resoudre_micro


RACINE = Path(__file__).resolve().parent
TAUX = 16_000
BLOC = 1_280


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--secondes", type=float, default=15.0)
    parser.add_argument("--gains", default="1,2,4,8")
    args = parser.parse_args()
    gains = [float(v) for v in args.gains.split(",") if v.strip()]

    conf = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8")) or {}
    appareil = _resoudre_micro(conf.get("micro", None))
    info = sd.query_devices(appareil, "input")
    taux_capture = int(round(info.get("default_samplerate") or TAUX))
    bloc_capture = int(round(BLOC * taux_capture / TAUX))
    modele = (
        Path(openwakeword.__file__).parent
        / "resources"
        / "models"
        / "hey_jarvis_v0.1.onnx"
    )
    meilleur_niveau = 0.0
    blocs = max(1, int(args.secondes * TAUX / BLOC))
    audio = []
    print(
        f"Calibration pendant {args.secondes:.0f} s. "
        f"Micro {taux_capture} Hz -> {TAUX} Hz. "
        "Dites plusieurs fois : Hey Jarvis."
    )
    debut = time.monotonic()
    with sd.InputStream(
        samplerate=taux_capture,
        channels=1,
        dtype="float32",
        device=appareil,
        blocksize=bloc_capture,
    ) as flux:
        for _ in range(blocs):
            bloc, _ = flux.read(bloc_capture)
            mono = bloc[:, 0]
            if taux_capture != TAUX:
                facteur = gcd(TAUX, taux_capture)
                mono = resample_poly(
                    mono, TAUX // facteur, taux_capture // facteur
                ).astype(np.float32)
            niveau = float(np.sqrt(np.mean(mono**2)))
            meilleur_niveau = max(meilleur_niveau, niveau)
            audio.append(mono)

    print(f"Capture terminée : niveau_max={meilleur_niveau:.4f}")
    for gain in gains:
        detecteur = Model(wakeword_model_paths=[str(modele)])
        meilleur_score = 0.0
        saturation = 0
        echantillons = 0
        for mono in audio:
            amplifie = mono * gain
            saturation += int(np.count_nonzero(np.abs(amplifie) > 1.0))
            echantillons += amplifie.size
            pcm = (np.clip(amplifie, -1, 1) * 32767).astype(np.int16)
            scores = detecteur.predict(pcm)
            meilleur_score = max(
                meilleur_score,
                max(float(np.max(v)) for v in scores.values()),
            )
        taux_saturation = 100 * saturation / max(1, echantillons)
        print(
            f"RESULTAT gain={gain:g} score_max={meilleur_score:.3f} "
            f"sat={taux_saturation:.3f}%"
        )
    print(f"Analyse terminée en {time.monotonic() - debut:.1f}s")


if __name__ == "__main__":
    main()
