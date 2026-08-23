"""Statistiques systeme : GPU (temperature, usage, VRAM), CPU, RAM, disque.

- GPU NVIDIA : pynvml (nvidia-ml-py) -> temperature, usage, VRAM.
- GPU Apple  : la puce est unifiee ; system_profiler donne le modele et le
  nombre de coeurs. La temperature n'est PAS exposee par macOS sans droits
  administrateur : on ne l'invente pas, on le dit.
- Le reste (CPU, RAM, disque) via psutil, identique sur les trois systemes.

Le resultat complet est renvoye a Claude, qui repond de facon courte et
naturelle selon la question ("ma temperature GPU ?" -> juste le GPU).
"""
from core import plateforme
from core.registre import outil


def _gpu_nvidia():
    """Ligne GPU NVIDIA, ou None si indisponible."""
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
        util = pynvml.nvmlDeviceGetUtilizationRates(h).gpu
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        vram = round(mem.used / mem.total * 100) if mem.total else 0
        pynvml.nvmlShutdown()
        return f"GPU {temp} degres, {util}% d'utilisation, VRAM a {vram}%"
    except Exception:
        return None


def _gpu_apple():
    """Ligne GPU Apple (memoire unifiee), ou None."""
    nom = plateforme.infos_gpu()
    if not nom:
        return None
    return (f"{nom}, memoire unifiee partagee avec la RAM ; macOS n'expose pas "
            "la temperature du GPU sans droits administrateur")


@outil(
    nom="get_system_stats",
    mcp_expose=True,
    description="Donne l'etat de la machine : temperature et usage du GPU, VRAM, "
                "usage CPU, RAM, espace disque. A utiliser pour 'ma temperature GPU', "
                "'ca va niveau perfs', 'combien de RAM utilisee', 'il reste combien "
                "de disque'. Reponds de facon courte selon ce qui est demande.",
)
def get_system_stats() -> str:
    parties = []

    gpu = _gpu_nvidia()
    if gpu is None and plateforme.EST_MAC:
        gpu = _gpu_apple()
    parties.append(gpu or "GPU indisponible (pilote NVIDIA ou pynvml absent)")

    try:
        import psutil
        cpu = round(psutil.cpu_percent(interval=0.3))
        ram = round(psutil.virtual_memory().percent)
        disque = psutil.disk_usage(plateforme.racine_disque())
        libre = round(disque.free / (1024 ** 3))
        parties.append(f"CPU {cpu}%, RAM {ram}%, "
                       f"disque {plateforme.nom_disque()} {libre} Go libres")
    except Exception:
        parties.append("stats systeme indisponibles")

    return ". ".join(parties) + "."
