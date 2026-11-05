"""Abstraction du modele de langage : le reste du code ignore quel provider tourne.

Trois implementations, choisies par config.yaml :
  - OpenAIProvider : Responses API (cloud recommande, GPT-6 Astra disponible).
  - ClaudeProvider : API Anthropic (repli compatible pour les anciennes configs).
  - OllamaProvider : Ollama en local (http://localhost:11434), 100% offline.

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
from core import cloud

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


# --------------------------------------------------------------- OpenAI (cloud)

class OpenAIProvider(ProviderLLM):
    """Adaptateur Responses API -> forme historique comprise par jarvis14."""

    nom = "OpenAI"

    def __init__(self, modele=None, qualite=False):
        self.modele = modele or cloud.modele(qualite=qualite)
        self.qualite = qualite
        self.client = cloud.client_openai()

    def disponible(self):
        return self.client is not None

    @staticmethod
    def _outils(outils):
        return [{
            "type": "function",
            "name": o["name"],
            "description": o.get("description", ""),
            "parameters": o.get("input_schema", {
                "type": "object", "properties": {}}),
            "strict": False,
        } for o in outils]

    @staticmethod
    def _contenu_image(contenu):
        for item in contenu or []:
            if not isinstance(item, dict) or item.get("type") != "image":
                continue
            src = item.get("source", {}) or {}
            if src.get("type") == "base64" and src.get("data"):
                mime = src.get("media_type", "image/jpeg")
                return f"data:{mime};base64,{src['data']}"
        return ""

    def _traduire(self, historique):
        """Historique Anthropic interne -> items Responses API."""
        items = []
        for message in historique:
            role = message.get("role", "user")
            contenu = message.get("content", "")
            if isinstance(contenu, str):
                items.append({"role": role, "content": contenu})
                continue

            if role == "assistant":
                textes = [b.text for b in (contenu or [])
                          if getattr(b, "type", None) == "text" and b.text]
                if textes:
                    items.append({"role": "assistant", "content": " ".join(textes)})
                for bloc in contenu or []:
                    if getattr(bloc, "type", None) != "tool_use":
                        continue
                    items.append({
                        "type": "function_call",
                        "call_id": bloc.id,
                        "name": bloc.name,
                        "arguments": json.dumps(bloc.input or {}, ensure_ascii=False),
                    })
                continue

            # Les resultats d'outils sont des items autonomes. Une capture est
            # ajoutee comme image utilisateur juste apres son function output.
            for resultat in contenu or []:
                if not isinstance(resultat, dict) or resultat.get("type") != "tool_result":
                    continue
                sortie = resultat.get("content", "")
                image = self._contenu_image(sortie) if isinstance(sortie, list) else ""
                items.append({
                    "type": "function_call_output",
                    "call_id": resultat.get("tool_use_id", ""),
                    "output": "Capture d'ecran disponible." if image else str(sortie),
                })
                if image:
                    items.append({"role": "user", "content": [{
                        "type": "input_image", "image_url": image,
                    }]})
        return items

    def repondre(self, systeme, historique, outils):
        kwargs = {
            "model": self.modele,
            "instructions": systeme,
            "input": self._traduire(historique),
            "max_output_tokens": int(reglage("openai.max_output_tokens", 2048)),
            "store": False,
        }
        outils_api = self._outils(outils)
        if outils_api:
            kwargs["tools"] = outils_api
            kwargs["parallel_tool_calls"] = True
        raisonnement = cloud._raisonnement(self.modele, self.qualite)
        if raisonnement:
            kwargs["reasoning"] = raisonnement
        rep = self.client.responses.create(**kwargs)
        cloud.enregistrer_usage(rep, "OpenAI (Jarvis)", self.modele)

        blocs = []
        texte = (getattr(rep, "output_text", "") or "").strip()
        if texte:
            blocs.append(Bloc("text", text=texte))
        for item in getattr(rep, "output", []) or []:
            if getattr(item, "type", None) != "function_call":
                continue
            brut = getattr(item, "arguments", "{}") or "{}"
            try:
                arguments = json.loads(brut) if isinstance(brut, str) else dict(brut)
            except (ValueError, TypeError):
                LOG.warning("OpenAI: arguments outil invalides (%s)", brut)
                arguments = {}
            blocs.append(Bloc(
                "tool_use",
                id=getattr(item, "call_id", None) or getattr(item, "id", None),
                name=getattr(item, "name", ""),
                input=arguments,
            ))
        stop = "tool_use" if any(b.type == "tool_use" for b in blocs) else "end"
        return Reponse(stop, blocs)


# --------------------------------------------------------------- Claude (cloud)

class ClaudeProvider(ProviderLLM):
    nom = "Claude"

    def __init__(self, modele=None):
        import anthropic
        cle = reglage("anthropic.cle", "")
        self.modele = modele or reglage("anthropic.modele", "claude-haiku-4-5")
        # Memes delais que le client OpenAI : sans eux, le SDK attend jusqu'a
        # 600 s par essai (3 essais) et un appel bloque fige la voix.
        self.client = anthropic.Anthropic(
            api_key=cle,
            timeout=float(reglage("anthropic.timeout", 90)),
            max_retries=int(reglage("anthropic.max_retries", 1)),
        ) if cle else None

    def disponible(self):
        return self.client is not None

    @staticmethod
    def _outils_historique(historique):
        """Definitions des outils deja appeles dans l'historique ([] s'il n'y en a pas).

        L'API refuse un historique qui contient des blocs tool_use/tool_result
        si la requete ne definit aucun outil. Les vrais schemas sont repris du
        registre quand il les connait, sinon une definition minimale suffit."""
        noms, present = [], False
        for message in historique:
            contenu = message.get("content")
            if isinstance(contenu, str):
                continue
            for bloc in contenu or []:
                if isinstance(bloc, dict):
                    type_, nom = bloc.get("type"), bloc.get("name")
                else:   # bloc du SDK ou Bloc
                    type_, nom = getattr(bloc, "type", None), getattr(bloc, "name", None)
                if type_ in ("tool_use", "tool_result"):
                    present = True
                if type_ == "tool_use" and nom and nom not in noms:
                    noms.append(nom)
        if not present:
            return []
        try:
            from core import registre
            connus = {s["name"]: s for s in registre.schemas_api()}
        except Exception:
            connus = {}
        return [connus.get(nom) or {
            "name": nom, "description": "Outil deja utilise dans la conversation.",
            "input_schema": {"type": "object", "properties": {}},
        } for nom in (noms or ["outil_precedent"])]

    def repondre(self, systeme, historique, outils):
        # La reponse native Anthropic a deja la bonne forme (.stop_reason/.content).
        kwargs = {
            "model": self.modele,
            "max_tokens": 1024,
            "system": [{"type": "text", "text": systeme,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": historique,
        }
        if outils:
            kwargs["tools"] = outils
        else:
            # Phrase sans outil (« merci ») apres un tour qui en a utilise un :
            # on redeclare ces outils mais le tour reste sans action.
            deja_utilises = self._outils_historique(historique)
            if deja_utilises:
                kwargs["tools"] = deja_utilises
                kwargs["tool_choice"] = {"type": "none"}
        rep = self.client.messages.create(**kwargs)
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
        corps = {
            "model": self.modele, "messages": messages, "tools": tools,
            "stream": False, "think": bool(reglage("ollama.think", False)),
            "options": {"temperature": 0.3}}
        if not tools:
            corps.pop("tools")
        r = requests.post(f"{self.hote}/api/chat", timeout=120, json=corps)
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


def llm():
    """Provider LLM courant selon le mode (local | hybride | qualite).

    - local   : Ollama.
    - hybride : cloud economique (OpenAI par defaut) - reflexes + vision.
    - qualite : cloud fort (GPT-6 Astra par defaut)."""
    global _LLM
    if _LLM is None:
        from core.routage import mode_actuel
        m = mode_actuel()
        if m == "local":
            _LLM = OllamaProvider()
        else:
            qualite = m == "qualite"
            if cloud.fournisseur() == "openai":
                _LLM = OpenAIProvider(cloud.modele(qualite=qualite), qualite=qualite)
            else:
                _LLM = ClaudeProvider(cloud.modele(qualite=qualite))
        LOG.info("provider LLM : %s (mode %s, modele %s)",
                 _LLM.nom, m, getattr(_LLM, "modele", "-"))
    return _LLM


def reinitialiser():
    """Force la reconstruction du provider au prochain llm() (apres un switch de mode)."""
    global _LLM
    _LLM = None
