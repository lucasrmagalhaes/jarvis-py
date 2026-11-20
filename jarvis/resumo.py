"""Página do painel com a revisão e o resumo dos pedidos, sem texto de nota."""

from datetime import datetime
from zoneinfo import ZoneInfo

from .comandos import rotulo
from .pedidos import summary
from .review import _today, review_stats


def current_moment(root):
    zone = ZoneInfo("America/Sao_Paulo")
    if root is not None:
        try:
            from .routines import load_places

            zone = load_places(root).tz
        except Exception:
            zone = ZoneInfo("America/Sao_Paulo")
    return datetime.now(zone)


def build_resumo(root, now=None):
    moment = now or current_moment(root)
    today = _today(root, moment)
    stats = review_stats(root, today)
    usage = summary()
    rows = []
    for row in usage.get("por_intencao") or []:
        intent = row.get("intencao") or "chat"
        rows.append(
            {
                "intencao": intent,
                "rotulo": rotulo(intent),
                "vezes": int(row.get("vezes") or 0),
                "media_ms": _ms(row.get("media")),
            }
        )
    from .__version__ import __version__

    return {
        "versao": __version__,
        "revisao": {
            "vencidos": int(stats.get("vencidos") or 0),
            "feitos_hoje": int(stats.get("feitos_hoje") or 0),
            "sequencia": int(stats.get("sequencia") or 0),
        },
        "pedidos": {
            "total": int(usage.get("total") or 0),
            "media_ms": _ms(usage.get("media")),
            "por_intencao": rows,
        },
    }


def render_resumo(payload, token):
    review = payload.get("revisao") or {}
    usage = payload.get("pedidos") or {}
    rows = usage.get("por_intencao") or []
    if rows:
        body = "".join(
            "<tr><td>{rotulo}</td><td>{vezes}</td><td>{media} ms</td></tr>".format(
                rotulo=_esc(row.get("rotulo")),
                vezes=int(row.get("vezes") or 0),
                media=int(row.get("media_ms") or 0),
            )
            for row in rows
        )
        table = (
            "<table><thead><tr><th>Intenção</th><th>Vezes</th>"
            "<th>Duração média</th></tr></thead><tbody>"
            + body
            + "</tbody></table>"
        )
    else:
        table = "<p>Nenhum pedido registrado.</p>"
    streak = int(review.get("sequencia") or 0)
    streak_label = "1 dia" if streak == 1 else f"{streak} dias"
    back = "/?t=" + _esc(token)
    return """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Resumo do Jarvis</title>
<style>
body {{ margin: 0; background: #061120; color: #cfe9f7; font: 15px/1.5 Menlo, Consolas, monospace; }}
main {{ max-width: 720px; margin: 0 auto; padding: 28px 20px 48px; }}
a {{ color: #8ae6ff; }}
h1 {{ font-weight: 600; letter-spacing: 0.18em; font-size: 20px; }}
section {{ border: 1px solid rgba(80, 180, 235, 0.2); padding: 16px 18px; margin-top: 18px; }}
dl {{ display: grid; grid-template-columns: 10em 1fr; gap: 6px 12px; margin: 0; }}
dt {{ color: #5f8aa6; }}
dd {{ margin: 0; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid rgba(80, 180, 235, 0.16); }}
</style>
</head>
<body>
<main>
<p><a href="{back}">Voltar ao painel</a></p>
<h1>Resumo</h1>
<p>Versão {versao}</p>
<section>
<h2>Revisão</h2>
<dl>
<dt>Vencidos</dt><dd>{due}</dd>
<dt>Feitos hoje</dt><dd>{done}</dd>
<dt>Sequência</dt><dd>{streak}</dd>
</dl>
</section>
<section>
<h2>Pedidos</h2>
<p>{total} no log. Duração média {average} ms.</p>
{table}
</section>
</main>
</body>
</html>
""".format(
        back=back,
        versao=_esc(payload.get("versao") or ""),
        due=int(review.get("vencidos") or 0),
        done=int(review.get("feitos_hoje") or 0),
        streak=_esc(streak_label),
        total=int(usage.get("total") or 0),
        average=int(usage.get("media_ms") or 0),
        table=table,
    )


def _ms(seconds):
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return 0
    if value < 0:
        return 0
    return int(round(value * 1000))


def _esc(value):
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
