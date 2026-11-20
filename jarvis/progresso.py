"""Barra de progresso em texto puro, estável no Windows."""


def barra(feito, total, segundos, largura=24):
    total = max(int(total or 0), 1)
    feito = min(max(int(feito or 0), 0), total)
    cheio = largura if feito >= total else int(largura * feito / total)
    eta = 0.0
    if 0 < feito < total:
        eta = float(segundos) * (total - feito) / feito
    return (
        "Indice ["
        + ("#" * cheio)
        + ("-" * (largura - cheio))
        + "] "
        + str(feito)
        + "/"
        + str(total)
        + " "
        + str(int(100 * feito / total))
        + "% ETA "
        + relogio(eta)
    )


def relogio(segundos):
    total = max(0, int(float(segundos) + 0.5))
    minutos, resto = divmod(total, 60)
    horas, minutos = divmod(minutos, 60)
    if horas:
        return f"{horas:d}:{minutos:02d}:{resto:02d}"
    return f"{minutos:02d}:{resto:02d}"
