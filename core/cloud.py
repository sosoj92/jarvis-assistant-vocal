"""Client cloud commun a Jarvis.

OpenAI (Responses API) et Anthropic/Claude sont les deux fournisseurs cloud
intégrés. Le choix explicite vit dans ``cloud.fournisseur`` ; la détection des
anciennes configurations est conservée pour éviter une migration brutale.

Ce module centralise aussi les appels texte/vision utilises hors de la boucle
principale (indexeur, navigateur, reservations, appels). Les secrets ne quittent
jamais ``config.yaml`` et ne sont jamais journalises.
"""
from __future__ import annotations

import json
import logging

from core.config import reglage

LOG = logging.getLogger("jarvis")


def fournisseur() -> str:
    """Fournisseur cloud actif : openai, anthropic (Claude), gemini ou mistral."""
    choix = str(reglage("cloud.fournisseur", "") or "").strip().lower()
    if choix in {"openai", "anthropic", "gemini", "mistral"}:
        return choix
    # Une ancienne config sans bloc cloud continue de fonctionner. Des qu'une
    # cle OpenAI est ajoutee, OpenAI devient naturellement le choix par defaut.
    return "openai" if reglage("openai.cle", "") else "anthropic"


def _modeles_fournisseur() -> dict:
    """Defauts par fournisseur : (economique, qualite)."""
    if fournisseur() == "mistral":
        return {"cle": "mistral.modele", "cle_qualite": "mistral.modele_qualite",
                "eco": "mistral-small-latest", "fort": "mistral-large-latest"}
    if fournisseur() == "openai":
        return {"cle": "openai.modele", "cle_qualite": "openai.modele_qualite",
                "eco": "gpt-5.6-terra", "fort": "gpt-6-astra"}
    return {"cle": "anthropic.modele", "cle_qualite": "anthropic.modele_qualite",
            "eco": "claude-haiku-4-5", "fort": "claude-sonnet-4-5"}


def _surcharge_compatible(candidat: str) -> bool:
    """Une surcharge de modele est-elle utilisable par le fournisseur actif ?

    Une ancienne config peut encore contenir reservation.modele=claude-... ou
    gpt-... lors d'un changement de fournisseur. On ignore alors seulement
    cette surcharge obsolete plutot que de casser le sous-pipeline.
    """
    f = fournisseur()
    p = candidat.lower()
    if f == "openai":
        return not p.startswith("claude")
    if f == "anthropic":
        return not p.startswith(("gpt-", "o1", "o3", "o4"))
    if f == "mistral":
        return p.startswith(("mistral", "ministral", "pixtral", "open-mistral"))
    return True


def modele(qualite: bool = False, surcharge: str = "") -> str:
    if surcharge and _surcharge_compatible(str(surcharge)):
        return str(surcharge)
    m = _modeles_fournisseur()
    return str(reglage(m["cle_qualite"] if qualite else m["cle"], m["fort"] if qualite else m["eco"]))


def client_openai():
    cle = str(reglage("openai.cle", "") or "").strip()
    if not cle:
        return None
    from openai import OpenAI
    return OpenAI(api_key=cle, timeout=float(reglage("openai.timeout", 90)),
                  max_retries=int(reglage("openai.max_retries", 1)))


def client_anthropic():
    cle = str(reglage("anthropic.cle", "") or "").strip()
    if not cle:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=cle)


def client_mistral():
    """Client Mistral AI (API compatible OpenAI, chat completions)."""
    cle = str(reglage("mistral.cle", "") or "").strip()
    if not cle:
        return None
    from openai import OpenAI
    return OpenAI(
        api_key=cle,
        base_url=str(reglage("mistral.url", "https://api.mistral.ai/v1") or "").rstrip("/"),
        timeout=float(reglage("mistral.timeout", 90)),
        max_retries=int(reglage("mistral.max_retries", 1)),
    )


def disponible() -> bool:
    f = fournisseur()
    if f == "mistral":
        return bool(client_mistral())
    return bool(client_openai() if f == "openai" else client_anthropic())


def enregistrer_usage(rep, nom_fournisseur: str, nom_modele: str) -> None:
    """Enregistre tokens et cache sans jamais laisser la telemetrie casser l'appel."""
    try:
        usage = getattr(rep, "usage", None)
        if usage is None:
            return
        if nom_fournisseur.lower().startswith("openai"):
            entree = int(getattr(usage, "input_tokens", 0) or 0)
            sortie = int(getattr(usage, "output_tokens", 0) or 0)
            details = getattr(usage, "input_tokens_details", None)
            cache = int(getattr(details, "cached_tokens", 0) or 0)
            # Chez OpenAI, input_tokens inclut deja le cache.
            entree_hors_cache = max(0, entree - cache)
            from core import budget
            budget.enregistrer(nom_fournisseur, nom_modele, entree_hors_cache,
                                sortie, cache_read=cache)
        else:
            from core import budget
            budget.enregistrer(
                nom_fournisseur, nom_modele,
                getattr(usage, "input_tokens", 0) or 0,
                getattr(usage, "output_tokens", 0) or 0,
                cache_read=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_creation=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            )
    except Exception:
        LOG.exception("comptage usage cloud")


def _raisonnement(nom_modele: str, qualite: bool = False):
    """Option Responses API uniquement pour les familles qui la supportent."""
    if not str(nom_modele).lower().startswith(("gpt-5", "gpt-6")):
        return None
    cle = "openai.raisonnement_qualite" if qualite else "openai.raisonnement"
    effort = str(reglage(cle, "high" if qualite else "low") or "").lower()
    autorises = {"none", "low", "medium", "high", "xhigh", "max"}
    if str(nom_modele).lower().startswith("gpt-6") and effort == "none":
        effort = "low"
    return {"effort": effort} if effort in autorises else None


def repondre_texte(systeme: str, historique: list, max_tokens: int = 500,
                   nom_modele: str = "", qualite: bool = False) -> str:
    """Reponse texte cloud, pour les sous-pipelines sans appels d'outils."""
    provider = fournisseur()
    cible = modele(qualite=qualite, surcharge=nom_modele)
    if provider == "openai":
        client = client_openai()
        if client is None:
            raise RuntimeError("cle OpenAI absente (openai.cle)")
        kwargs = {
            "model": cible,
            "instructions": systeme,
            "input": historique,
            # Ce plafond inclut les tokens de raisonnement. Une limite vocale de
            # 150 tokens serait sinon consommee avant tout texte visible.
            "max_output_tokens": max(max_tokens, 1024),
            "store": False,
        }
        raisonnement = _raisonnement(cible, qualite)
        if raisonnement:
            kwargs["reasoning"] = raisonnement
        rep = client.responses.create(**kwargs)
        enregistrer_usage(rep, "OpenAI (Jarvis)", cible)
        return (rep.output_text or "").strip()

    if provider == "mistral":
        return _mistral_repondre_texte(cible, systeme, historique, max_tokens)

    client = client_anthropic()
    if client is None:
        raise RuntimeError("cle Anthropic absente (anthropic.cle)")
    rep = client.messages.create(model=cible, max_tokens=max_tokens,
                                 system=systeme, messages=historique)
    enregistrer_usage(rep, "Claude (Jarvis)", cible)
    return "".join(b.text for b in rep.content
                   if getattr(b, "type", None) == "text").strip()


def _mistral_messages(systeme: str, historique: list) -> list:
    """Historique Anthropic interne -> messages chat completions.

    L'historique de Jarvis est soit du texte brut (content str), soit des
    blocs Anthropic (tool_use / tool_result). Mistral suit le format OpenAI :
    appels d'outils cote assistant, resultats cote user.
    """
    messages = [{"role": "system", "content": systeme}]
    for message in historique:
        role = message.get("role", "user")
        contenu = message.get("content", "")
        if isinstance(contenu, str):
            messages.append({"role": role, "content": contenu})
            continue
        if role == "assistant":
            textes = [b.text for b in (contenu or [])
                      if getattr(b, "type", None) == "text" and b.text]
            appels = []
            for bloc in contenu or []:
                if getattr(bloc, "type", None) != "tool_use":
                    continue
                appels.append({
                    "id": bloc.id or f"appel_{len(appels)}",
                    "type": "function", "function": {
                        "name": bloc.name,
                        "arguments": json.dumps(bloc.input or {}, ensure_ascii=False)},
                })
            if textes or appels:
                messages.append({"role": "assistant",
                                 "content": " ".join(textes) or None,
                                 "tool_calls": appels or None})
            continue
        for resultat in contenu or []:
            if not isinstance(resultat, dict) or resultat.get("type") != "tool_result":
                continue
            sortie = resultat.get("content", "")
            texte_sortie = "".join(
                b.get("text", "") if isinstance(b, dict) else ""
                for b in (sortie if isinstance(sortie, list) else []))
            messages.append({
                "role": "tool",
                "tool_call_id": resultat.get("tool_use_id", ""),
                "content": str(sortie) if isinstance(sortie, str) else (texte_sortie or ""),
            })
    return messages


def _mistral_repondre_texte(cible: str, systeme: str, historique: list,
                            max_tokens: int) -> str:
    client = client_mistral()
    if client is None:
        raise RuntimeError("cle Mistral absente (mistral.cle)")
    rep = client.chat.completions.create(
        model=cible,
        messages=_mistral_messages(systeme, historique),
        max_tokens=max(max_tokens, 1024),
    )
    enregistrer_usage(rep, "Mistral (Jarvis)", cible)
    return (rep.choices[0].message.content or "").strip()


def repondre_vision(systeme: str, texte: str, image_b64: str,
                    max_tokens: int = 700, nom_modele: str = "",
                    qualite: bool = False) -> str:
    """Réponse visuelle ponctuelle sans catalogue d'outils ni boucle opérateur."""
    provider = fournisseur()
    cible = modele(qualite=qualite, surcharge=nom_modele)
    if provider == "openai":
        client = client_openai()
        if client is None:
            raise RuntimeError("cle OpenAI absente (openai.cle)")
        kwargs = {
            "model": cible,
            "instructions": systeme,
            "input": [{"role": "user", "content": [
                {"type": "input_image",
                 "image_url": f"data:image/jpeg;base64,{image_b64}"},
                {"type": "input_text", "text": texte},
            ]}],
            "max_output_tokens": max(max_tokens, 1024),
            "store": False,
        }
        raisonnement = _raisonnement(cible, qualite)
        if raisonnement:
            kwargs["reasoning"] = raisonnement
        rep = client.responses.create(**kwargs)
        enregistrer_usage(rep, "OpenAI (Jarvis)", cible)
        return (rep.output_text or "").strip()

    if provider == "mistral":
        client = client_mistral()
        if client is None:
            raise RuntimeError("cle Mistral absente (mistral.cle)")
        rep = client.chat.completions.create(
            model=cible,
            messages=[
                {"role": "system", "content": systeme},
                {"role": "user", "content": [
                    {"type": "text", "text": texte},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}"}},
                ]},
            ],
            max_tokens=max_tokens,
        )
        enregistrer_usage(rep, "Mistral (Jarvis)", cible)
        return (rep.choices[0].message.content or "").strip()

    client = client_anthropic()
    if client is None:
        raise RuntimeError("cle Anthropic absente (anthropic.cle)")
    rep = client.messages.create(
        model=cible, max_tokens=max_tokens, system=systeme,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
             "media_type": "image/jpeg", "data": image_b64}},
            {"type": "text", "text": texte},
        ]}],
    )
    enregistrer_usage(rep, "Claude (Jarvis)", cible)
    return "".join(b.text for b in rep.content
                   if getattr(b, "type", None) == "text").strip()


def decider_action_vision(systeme: str, texte: str, image_b64: str,
                          schema: dict, nom_outil: str = "agir",
                          description: str = "Decide de la prochaine action.",
                          nom_modele: str = "", qualite: bool = False,
                          fournisseur_force: str = "") -> dict:
    """Demande UNE action structuree a partir d'une capture JPEG."""
    provider = (fournisseur_force or fournisseur()).strip().lower()
    cible = str(nom_modele or "").strip()
    incompatible = ((provider == "openai" and cible.lower().startswith("claude"))
                    or (provider == "anthropic"
                        and cible.lower().startswith(("gpt-", "o1", "o3", "o4"))))
    if not cible or incompatible:
        cible = modele(qualite=qualite)
    if provider == "mistral":
        client = client_mistral()
        if client is None:
            raise RuntimeError("cle Mistral absente (mistral.cle)")
        rep = client.chat.completions.create(
            model=cible,
            messages=[
                {"role": "system", "content": systeme},
                {"role": "user", "content": [
                    {"type": "text", "text": texte},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}"}},
                ]},
            ],
            tools=[{"type": "function", "function": {
                "name": nom_outil, "description": description,
                "parameters": schema}}],
            tool_choice={"type": "function", "function": {"name": nom_outil}},
            max_tokens=1200,
        )
        enregistrer_usage(rep, "Mistral (Jarvis)", cible)
        appel = getattr(rep.choices[0].message, "tool_calls", None) or []
        if appel:
            brut = appel[0].function.arguments or "{}"
            return json.loads(brut) if isinstance(brut, str) else dict(brut)
        return {"action": "bloque", "raison": "pas de reponse exploitable"}
    if provider == "openai":
        client = client_openai()
        if client is None:
            raise RuntimeError("cle OpenAI absente (openai.cle)")
        kwargs = {
            "model": cible,
            "instructions": systeme,
            "input": [{"role": "user", "content": [
                {"type": "input_image",
                 "image_url": f"data:image/jpeg;base64,{image_b64}"},
                {"type": "input_text", "text": texte},
            ]}],
            "tools": [{"type": "function", "name": nom_outil,
                       "description": description, "parameters": schema,
                       "strict": False}],
            "tool_choice": {"type": "function", "name": nom_outil},
            "max_output_tokens": 1200,
            "store": False,
        }
        raisonnement = _raisonnement(cible, qualite)
        if raisonnement:
            kwargs["reasoning"] = raisonnement
        rep = client.responses.create(**kwargs)
        enregistrer_usage(rep, "OpenAI (Jarvis)", cible)
        for item in rep.output:
            if getattr(item, "type", None) == "function_call":
                args = getattr(item, "arguments", "{}") or "{}"
                return json.loads(args) if isinstance(args, str) else dict(args)
        return {"action": "bloque", "raison": "pas de reponse exploitable"}

    client = client_anthropic()
    if client is None:
        raise RuntimeError("cle Anthropic absente (anthropic.cle)")
    rep = client.messages.create(
        model=cible, max_tokens=700, system=systeme,
        tools=[{"name": nom_outil, "description": description,
                "input_schema": schema}],
        tool_choice={"type": "tool", "name": nom_outil},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
             "media_type": "image/jpeg", "data": image_b64}},
            {"type": "text", "text": texte},
        ]}],
    )
    enregistrer_usage(rep, "Claude (Jarvis)", cible)
    for bloc in rep.content:
        if getattr(bloc, "type", None) == "tool_use":
            return bloc.input
    return {"action": "bloque", "raison": "pas de reponse exploitable"}
