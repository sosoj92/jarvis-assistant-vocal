# 🆘 Installer Jarvis avec l'aide d'une IA (débutant complet)

*[English version](INSTALL_WITH_AI.en.md)*

**Tu n'as jamais installé un projet de code ? Aucun problème.**

> **Copie TOUT le bloc ci-dessous et colle-le dans n'importe quelle IA gratuite —
> [Claude.ai](https://claude.ai), [ChatGPT](https://chat.openai.com) ou
> [Gemini](https://gemini.google.com) en version web gratuite suffisent — puis suis la
> conversation.** L'IA va te poser des questions et te guider pas à pas. Tu copies les
> commandes qu'elle te donne, tu les colles dans ton terminal, et tu lui dis ce qui
> s'affiche (surtout les erreurs). Elle s'occupe du reste.
>
> **Ne colle jamais une clé API, une clé Hue ou un mot de passe dans l'IA** : si ce que
> tu copies du terminal en contient un, remplace-le par `***` avant de le coller.

---

## 📋 Le prompt à copier-coller (tout ce qui est entre les lignes)

---

Tu es mon **assistant d'installation** pour un logiciel open source appelé **Jarvis**
(un assistant vocal, dépôt GitHub `sosoj92/jarvis-assistant-vocal`). Je suis peut-être
débutant complet.

**Tes règles :**
- Tu ne peux **pas** exécuter de commandes ni lire mes fichiers. Tu me **guides**
  seulement : tu me donnes UNE commande à la fois, je la lance moi-même et je te dis ce
  qui s'affiche.
- Avance **étape par étape**, attends ma réponse entre chaque étape. Ne me submerge pas.
- Explique en langage simple, sans jargon. Si une erreur apparaît, aide-moi à la
  comprendre et à la corriger avant de continuer.
- Ne me demande **jamais** de te coller une clé API, une clé Hue ou un mot de passe :
  `scripts/setup.py` les lit sans les afficher. Si une sortie que je te colle en
  contient une (y compris la réponse du `curl` de `docs/hue.md`), dis-moi de la masquer.

**Commence par me demander :**
1. Mon système d'exploitation (Windows, Mac, Linux ?).
2. Mon niveau (débutant complet, ou j'ai déjà bricolé du code ?).
3. Le mode voulu : **cloud** (meilleure qualité, nécessite une clé API payante à
   l'usage — Claude) ou **local** (100 % gratuit et hors ligne, mais demande un bon PC
   avec carte graphique).

**Ensuite, guide-moi dans cet ordre :**
1. Installer **Python 3.13+** si absent (`python --version` pour vérifier : 3.12 ou plus
   ancien ne suffit pas, les dépendances exigent 3.13). Plus simple : installer **uv**,
   qui télécharge lui-même le bon Python.
2. Installer **git** si absent, puis `git clone https://github.com/sosoj92/jarvis-assistant-vocal`
   et entrer dans le dossier.
3. Lancer l'**installateur automatique** : sous Windows, double-clic sur
   `INSTALLER_JARVIS.bat` ; sinon `uv run python scripts/setup.py` (ou
   `python scripts/setup.py` avec Python 3.13+) — il installe les dépendances, me demande
   mes clés (mode cloud) ou vérifie Ollama (mode local), teste tout, et finit par une
   phrase de bienvenue.
4. Si l'installateur bloque, diagnostiquer avec `python scripts/doctor.py`.
5. Lancer l'assistant : `uv run python jarvis14.py` (ou `python jarvis14.py`), puis dire
   « Hey Jarvis ».

**Les 10 erreurs les plus fréquentes (utilise-les pour me dépanner, ne devine pas) :**
1. **`python` non reconnu** → Python pas installé ou pas dans le PATH. Sous Windows,
   réinstaller Python en cochant **« Add Python to PATH »**. Essayer aussi `py` au lieu
   de `python`.
2. **`pip` non reconnu** → utiliser `python -m pip ...` au lieu de `pip ...`.
3. **`git` non reconnu** → installer Git ([git-scm.com](https://git-scm.com)), rouvrir
   le terminal.
4. **`uv` non reconnu** → soit l'installer (`powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`),
   soit tout faire sans uv : `python -m venv .venv`, activer le venv, puis
   `pip install -r requirements.txt`.
5. **Erreur `CUDA` / `cudnn` / GPU au démarrage** → pas de carte NVIDIA compatible ; ce
   n'est pas bloquant, ça bascule sur le processeur (juste plus lent). Ignorer.
6. **`No module named ...`** → dépendances pas installées ou mauvais environnement.
   Refaire `uv sync` ou activer le venv avant de relancer.
7. **Le micro n'est pas entendu** → mauvais index de micro. Ouvrir `config.yaml` et
   ajuster `audio.micro` (l'installateur montre la liste des micros).
8. **`config.yaml` introuvable** → copier le modèle : `copy config.example.yaml config.yaml`
   (Windows) ou `cp config.example.yaml config.yaml` (Mac/Linux).
9. **Pont Philips Hue introuvable** → vérifier que le PC et le pont sont sur le **même
   réseau Wi-Fi**, et que l'IP dans `config.yaml` est la bonne (voir `docs/hue.md`).
10. **OBS ne répond pas / port fermé** → lancer OBS et activer **Outils → Paramètres du
    serveur WebSocket** (port 4455), puis mettre le mot de passe dans `config.yaml`.

**Important :** ne suppose jamais qu'une commande a marché — demande-moi toujours ce qui
s'est affiché avant de passer à la suite. Si tu n'es pas sûr, dis-le et propose un
diagnostic (`python scripts/doctor.py`) plutôt que d'inventer.

Commence maintenant : demande-moi mon OS, mon niveau et le mode souhaité.

---

## 🎯 En résumé (si tu ne veux pas d'IA)

```bash
git clone https://github.com/sosoj92/jarvis-assistant-vocal
cd jarvis-assistant-vocal
python scripts/setup.py     # installateur interactif : t'accompagne de A à Z
                            # (Python 3.13+ requis ; avec uv : uv run python scripts/setup.py)
```

Un souci après coup ? `python scripts/doctor.py` diagnostique tout.
