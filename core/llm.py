"""Abstraction du modele de langage : le reste du code ignore quel provider tourne.

Deux implementations, choisies par config.yaml (mode: cloud | local) :
  - ClaudeProvider  : API Anthropic (cloud, defaut).
  - OllamaProvider  : Ollama en local (http://localhost:11434), 100% offline.

Les deux exposent la meme methode `repondre(systeme, historique, outils)` et
renvoient un objet a la forme d'une reponse Anthropic (.stop_reason + .content,
chaque bloc ayant .type / .text / .name / .input / .id). Ainsi la boucle de
dialogue de jarvis14 ne change pas selon le provider.

L'historique reste au format "content blocks" d'Anthropic ; OllamaProvider le
traduit vers/depuis le format d'Ollama de facon interne.
"""
import json
import logging

# Magasin de certificats Windows (Malwarebytes intercepte le TLS : sans ca, les
# appels a l'API Anthropic echouent en "certificate verify failed").
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

from core.config import reglage

LOG = logging.getLogger("jarvis")


class Bloc:
    """Imite un bloc de contenu Anthropic (text ou tool_use)."""

    def __init__(self, type, text=None, id=None, name=None, input=None):
        self.type = type
        self.text = text
        self.id = id
        self.name = name
        self.input = input


class Reponse:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


# --------------------------------------------------------------- interface

class ProviderLLM:
    nom = "?"

    def disponible(self):
        return True

    def repondre(self, systeme, historique, outils):
        raise NotImplementedError


# --------------------------------------------------------------- Claude (cloud)

class ClaudeProvider(ProviderLLM):
    nom = "Claude"

    def __init__(self, modele=None):
        import anthropic
        cle = reglage("anthropic.cle", "")
        self.modele = modele or reglage("anthropic.modele", "claude-haiku-4-5")
        self.client = anthropic.Anthropic(api_key=cle) if cle else None

    def disponible(self):
        return self.client is not None

    def repondre(self, systeme, historique, outils):
        # La reponse native Anthropic a deja la bonne forme (.stop_reason/.content).
        rep = self.client.messages.create(
            model=self.modele,
            max_tokens=1024,
            system=[{"type": "text", "text": systeme,
                     "cache_control": {"type": "ephemeral"}}],
            messages=historique,
            tools=outils,
        )
        # Comptabilite (N9) : tokens + cout estime, par jour, cote Jarvis.
        try:
            u = getattr(rep, "usage", None)
            if u is not None:
                from core import budget
                budget.enregistrer(
                    "Claude (Jarvis)", self.modele,
                    getattr(u, "input_tokens", 0) or 0,
                    getattr(u, "output_tokens", 0) or 0,
                    cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
                    cache_creation=getattr(u, "cache_creation_input_tokens", 0) or 0)
        except Exception:
            pass
        return rep


# --------------------------------------------------------------- Gemini (cloud)

class GeminiProvider(ProviderLLM):
    """Google Gemini, alternative cloud a Claude.

    Interet principal : Google AI Studio offre un palier GRATUIT, et Gemini gere
    la VISION — contrairement au mode local, la capture d'ecran et le controle
    souris continuent donc de fonctionner.

    Comme pour Ollama, tout l'assistant parle le format Anthropic (blocs text /
    image / tool_use / tool_result) : ce provider traduit dans les deux sens.
    """

    nom = "Gemini"

    def __init__(self, modele=None):
        self.cle = reglage("gemini.cle", "")
        self.modele = modele or reglage("gemini.modele", "gemini-2.5-flash")
        self._client = None

    def disponible(self):
        return bool(self.cle)

    def client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.cle)
        return self._client

    # -- outils : schema JSON -> FunctionDeclaration ------------------------

    @staticmethod
    def _nettoyer_schema(schema):
        """Retire les mots-cles JSON Schema que Gemini refuse.

        Gemini n'accepte qu'un sous-ensemble d'OpenAPI : additionalProperties,
        $schema et consorts font echouer TOUTE la requete, pas seulement l'outil
        fautif. On elague donc en profondeur.
        """
        if not isinstance(schema, dict):
            return schema
        interdits = {"additionalProperties", "$schema", "$id", "definitions",
                     "$defs", "examples", "default", "title"}
        propre = {}
        for clef, valeur in schema.items():
            if clef in interdits:
                continue
            if clef == "properties" and isinstance(valeur, dict):
                propre[clef] = {k: GeminiProvider._nettoyer_schema(v)
                                for k, v in valeur.items()}
            elif clef == "items":
                propre[clef] = GeminiProvider._nettoyer_schema(valeur)
            else:
                propre[clef] = valeur
        return propre

    def _outils(self, outils):
        from google.genai import types
        declarations = []
        for o in outils:
            schema = self._nettoyer_schema(
                o.get("input_schema") or {"type": "object", "properties": {}})
            # Un outil sans parametre : Gemini veut un objet vide, pas None.
            if not schema.get("properties"):
                schema = {"type": "object", "properties": {}}
            declarations.append(types.FunctionDeclaration(
                name=o["name"], description=o.get("description", ""),
                parameters=schema))
        return [types.Tool(function_declarations=declarations)] if declarations else None

    # -- historique : format Anthropic -> contents Gemini -------------------

    def _traduire(self, historique):
        """(contents, noms) — noms mappe tool_use_id -> nom d'outil.

        Gemini identifie une reponse d'outil par le NOM de la fonction, la ou
        Anthropic utilise un identifiant. On garde donc la correspondance vue
        dans les tours precedents pour pouvoir renvoyer le bon nom.
        """
        from google.genai import types
        import base64

        contents, noms = [], {}
        for message in historique:
            role, contenu = message.get("role"), message.get("content")
            parts = []

            if isinstance(contenu, str):
                if contenu.strip():
                    parts.append(types.Part.from_text(text=contenu))
                if parts:
                    contents.append(types.Content(
                        role="user" if role == "user" else "model", parts=parts))
                continue

            for item in contenu or []:
                # Bloc objet (reponse precedente du modele)
                type_bloc = getattr(item, "type", None)
                if type_bloc == "text" and getattr(item, "text", ""):
                    parts.append(types.Part.from_text(text=item.text))
                    continue
                if type_bloc == "tool_use":
                    noms[item.id] = item.name
                    parts.append(types.Part.from_function_call(
                        name=item.name, args=item.input or {}))
                    continue

                if not isinstance(item, dict):
                    continue
                t = item.get("type")
                if t == "text" and item.get("text"):
                    parts.append(types.Part.from_text(text=item["text"]))
                elif t == "image":
                    src = item.get("source", {}) or {}
                    parts.append(types.Part.from_bytes(
                        data=base64.b64decode(src.get("data", "")),
                        mime_type=src.get("media_type", "image/jpeg")))
                elif t == "tool_use":
                    noms[item.get("id")] = item.get("name")
                    parts.append(types.Part.from_function_call(
                        name=item.get("name"), args=item.get("input") or {}))
                elif t == "tool_result":
                    nom = noms.get(item.get("tool_use_id"), "outil")
                    c = item.get("content")
                    if isinstance(c, list):
                        # Capture d'ecran : l'image part en piece jointe, et la
                        # reponse de fonction dit simplement qu'elle suit.
                        parts.append(types.Part.from_function_response(
                            name=nom, response={"result": "image ci-jointe"}))
                        for bloc in c:
                            if isinstance(bloc, dict) and bloc.get("type") == "image":
                                src = bloc.get("source", {}) or {}
                                parts.append(types.Part.from_bytes(
                                    data=base64.b64decode(src.get("data", "")),
                                    mime_type=src.get("media_type", "image/jpeg")))
                    else:
                        parts.append(types.Part.from_function_response(
                            name=nom, response={"result": str(c)}))

            if parts:
                contents.append(types.Content(
                    role="user" if role == "user" else "model", parts=parts))
        return contents, noms

    # -- reponse Gemini -> blocs Anthropic ---------------------------------

    def _parser(self, reponse):
        blocs = []
        candidats = getattr(reponse, "candidates", None) or []
        if candidats:
            for i, part in enumerate(getattr(candidats[0].content, "parts", None) or []):
                texte = getattr(part, "text", None)
                if texte and texte.strip():
                    blocs.append(Bloc("text", text=texte))
                appel = getattr(part, "function_call", None)
                if appel is not None and getattr(appel, "name", None):
                    blocs.append(Bloc("tool_use",
                                      id=getattr(appel, "id", None) or f"call_{i}",
                                      name=appel.name,
                                      input=dict(appel.args or {})))
        if not blocs:
            blocs.append(Bloc("text", text=""))
        stop = "tool_use" if any(b.type == "tool_use" for b in blocs) else "end"
        return Reponse(stop, blocs)

    def repondre(self, systeme, historique, outils):
        from google.genai import types
        contents, _ = self._traduire(historique)
        config = types.GenerateContentConfig(
            system_instruction=systeme,
            tools=self._outils(outils),
            temperature=float(reglage("gemini.temperature", 0.3)),
            max_output_tokens=int(reglage("gemini.max_tokens", 1024)),
        )
        reponse = self.client().models.generate_content(
            model=self.modele, contents=contents, config=config)

        try:                                   # comptabilite (N9), comme Claude
            u = getattr(reponse, "usage_metadata", None)
            if u is not None:
                from core import budget
                budget.enregistrer(
                    "Gemini (Jarvis)", self.modele,
                    getattr(u, "prompt_token_count", 0) or 0,
                    getattr(u, "candidates_token_count", 0) or 0)
        except Exception:
            pass
        return self._parser(reponse)


# --------------------------------------------------------------- Ollama (local)

class OllamaProvider(ProviderLLM):
    nom = "Ollama"

    def __init__(self):
        self.hote = reglage("ollama.hote", "http://localhost:11434").rstrip("/")
        self.modele = reglage("ollama.modele", "qwen3.5:4b")

    def disponible(self):
        try:
            import requests
            requests.get(f"{self.hote}/api/version", timeout=3)
            return True
        except Exception:
            return False

    # -- traduction historique Anthropic -> messages Ollama --
    def _traduire(self, systeme, historique):
        messages = [{"role": "system", "content": systeme}]
        for m in historique:
            role, contenu = m.get("role"), m.get("content")
            if role == "user":
                if isinstance(contenu, str):
                    messages.append({"role": "user", "content": contenu})
                else:
                    for item in contenu or []:
                        if not isinstance(item, dict):
                            continue
                        if item.get("type") == "tool_result":
                            c = item.get("content")
                            if isinstance(c, list):   # bloc image
                                c = "[image capturee — la vision n'est pas disponible en mode local]"
                            messages.append({"role": "tool", "content": str(c)})
                        elif item.get("type") == "image":
                            messages.append({"role": "user",
                                             "content": "[image — vision indisponible en local]"})
            else:  # assistant
                if isinstance(contenu, str):
                    messages.append({"role": "assistant", "content": contenu})
                else:
                    texte = " ".join(b.text for b in (contenu or [])
                                     if getattr(b, "type", None) == "text" and b.text)
                    appels = [b for b in (contenu or []) if getattr(b, "type", None) == "tool_use"]
                    msg = {"role": "assistant", "content": texte}
                    if appels:
                        msg["tool_calls"] = [
                            {"function": {"name": b.name, "arguments": b.input or {}}}
                            for b in appels]
                    messages.append(msg)
        return messages

    def _outils(self, outils):
        return [{"type": "function", "function": {
            "name": o["name"], "description": o["description"],
            "parameters": o.get("input_schema", {"type": "object", "properties": {}})}}
            for o in outils]

    def _chat(self, messages, tools, nudge=None):
        import requests
        if nudge:
            messages = messages + [{"role": "user", "content": nudge}]
        # think=false : desactive le "raisonnement" natif (qwen3.5, etc.). Sinon le
        # modele est tres lent et rend parfois ses appels d'outils en texte au lieu
        # de les executer. Un modele sans thinking ignore ce parametre.
        r = requests.post(f"{self.hote}/api/chat", timeout=120, json={
            "model": self.modele, "messages": messages, "tools": tools,
            "stream": False, "think": bool(reglage("ollama.think", False)),
            "options": {"temperature": 0.3}})
        r.raise_for_status()
        return r.json()

    def _parser(self, rep):
        msg = rep.get("message", {}) or {}
        blocs = []
        texte = (msg.get("content") or "").strip()
        if texte:
            blocs.append(Bloc("text", text=texte))
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function", {}) or {}
            args = fn.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)   # peut lever -> gere par le retry
            blocs.append(Bloc("tool_use", id=f"call_{i}", name=fn.get("name"), input=args or {}))
        stop = "tool_use" if any(b.type == "tool_use" for b in blocs) else "end"
        return Reponse(stop, blocs)

    def repondre(self, systeme, historique, outils):
        messages = self._traduire(systeme, historique)
        tools = self._outils(outils)
        try:
            return self._parser(self._chat(messages, tools))
        except Exception as e:
            LOG.warning("ollama: 1er essai en echec (%s), retry plus directif", e)
            # Retry unique, avec une consigne plus stricte sur l'appel d'outil.
            nudge = ("Rappel : pour agir, appelle l'outil approprie via un tool call "
                     "avec des arguments JSON valides ; sinon reponds simplement en texte.")
            try:
                return self._parser(self._chat(messages, tools, nudge=nudge))
            except Exception:
                LOG.exception("ollama: echec apres retry")
                return Reponse("end", [Bloc("text", text=(
                    "Desole, le modele local n'a pas reussi a traiter la demande "
                    "correctement. Reessaie en reformulant, ou repasse en mode cloud."))])


# --------------------------------------------------------------- fabrique

_LLM = None


def _provider_cloud(qualite=False):
    """Claude ou Gemini, selon `fournisseur` dans config.yaml.

    Deux axes independants : `mode` dit OU tourne le modele (local/cloud) et
    quel niveau, `fournisseur` dit QUEL service cloud. Les melanger dans un
    seul reglage rendrait impossible « Gemini en qualite ».
    """
    choix = (reglage("fournisseur", "claude") or "claude").lower().strip()
    if choix == "gemini":
        return GeminiProvider(reglage("gemini.modele_qualite", "gemini-2.5-pro")
                              if qualite else None)
    return ClaudeProvider(reglage("anthropic.modele_qualite", "claude-sonnet-4-5")
                          if qualite else None)


def llm():
    """Provider LLM courant selon le mode (local | hybride | qualite).

    - local   : Ollama.
    - hybride : cloud, modele economique — reflexes + vision.
    - qualite : cloud, modele fort.
    Le service cloud (Claude ou Gemini) vient du reglage `fournisseur`."""
    global _LLM
    if _LLM is None:
        from core.routage import mode_actuel
        m = mode_actuel()
        if m == "local":
            _LLM = OllamaProvider()
        else:
            _LLM = _provider_cloud(qualite=(m == "qualite"))
        LOG.info("provider LLM : %s (mode %s, modele %s)",
                 _LLM.nom, m, getattr(_LLM, "modele", "-"))
    return _LLM


def reinitialiser():
    """Force la reconstruction du provider au prochain llm() (apres un switch de mode)."""
    global _LLM
    _LLM = None
