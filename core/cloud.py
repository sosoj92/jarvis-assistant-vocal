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

# Profils par defaut : le mode hybride privilegie le meilleur compromis
# cout/latence pour les reflexes quotidiens. Les demandes de fond partent vers
# Hermes et le profil qualite reste disponible ponctuellement. Une valeur
# explicite dans config.yaml gagne toujours sur ces recommandations.
PROFILS_CLOUD = {
    "openai": {
        "hybride": "gpt-5.6-luna",
        "qualite": "gpt-6-astra",
    },
    "anthropic": {
        "hybride": "claude-haiku-4-5",
        "qualite": "claude-sonnet-4-5",
    },
}


def fournisseur() -> str:
    """Fournisseur cloud actif : openai ou anthropic."""
    choix = str(reglage("cloud.fournisseur", "") or "").strip().lower()
    if choix in {"openai", "anthropic"}:
        return choix
    # Une ancienne config sans bloc cloud continue de fonctionner. Des qu'une
    # cle OpenAI est ajoutee, OpenAI devient naturellement le choix par defaut.
    return "openai" if reglage("openai.cle", "") else "anthropic"


def modele_par_defaut(nom_fournisseur: str = "", qualite: bool = False) -> str:
    """Modele recommande pour un profil, sans lire ni modifier config.yaml."""
    nom_fournisseur = (nom_fournisseur or fournisseur()).strip().lower()
    if nom_fournisseur not in PROFILS_CLOUD:
        nom_fournisseur = "openai"
    profil = "qualite" if qualite else "hybride"
    return PROFILS_CLOUD[nom_fournisseur][profil]


def modele(qualite: bool = False, surcharge: str = "") -> str:
    if surcharge:
        candidat = str(surcharge)
        # Une ancienne config peut encore contenir reservation.modele=claude-...
        # lors du passage a OpenAI (ou l'inverse). On ignore alors seulement cette
        # surcharge obsolete plutot que de casser le sous-pipeline.
        if fournisseur() == "openai" and not candidat.lower().startswith("claude"):
            return candidat
        if fournisseur() == "anthropic" and not candidat.lower().startswith(("gpt-", "o1", "o3", "o4")):
            return candidat
    if fournisseur() == "openai":
        cle = "openai.modele_qualite" if qualite else "openai.modele"
        return str(reglage(cle, modele_par_defaut("openai", qualite))
                   or modele_par_defaut("openai", qualite))
    cle = "anthropic.modele_qualite" if qualite else "anthropic.modele"
    return str(reglage(cle, modele_par_defaut("anthropic", qualite))
               or modele_par_defaut("anthropic", qualite))


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


def disponible() -> bool:
    return bool(client_openai() if fournisseur() == "openai" else client_anthropic())


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

    client = client_anthropic()
    if client is None:
        raise RuntimeError("cle Anthropic absente (anthropic.cle)")
    rep = client.messages.create(model=cible, max_tokens=max_tokens,
                                 system=systeme, messages=historique)
    enregistrer_usage(rep, "Claude (Jarvis)", cible)
    return "".join(b.text for b in rep.content
                   if getattr(b, "type", None) == "text").strip()


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
