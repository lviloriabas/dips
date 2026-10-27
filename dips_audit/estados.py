"""Estados del DIP compartidos por el filtro y la auditoría."""

ACTIVOS = frozenset({"ACTV", "ACTIVE", "OPEN", "IN WORK", "PAUSE"})


def normalizar_estado(valor: str) -> str:
    """Quita la etiqueta de ICAM, conservando códigos de varias palabras como IN WORK."""
    return " ".join(valor.split("(", 1)[0].upper().split())
