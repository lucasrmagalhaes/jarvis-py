"""Consultas somente leitura: Jira, GitHub e Gmail.

Sem configuração, cada uma devolve uma frase curta. Nenhuma envia, comenta ou altera.
"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from email.header import decode_header, make_header
from email.parser import Parser

from . import config
from .log import LOG

JIRA_MISSING = (
    "O Jira não está configurado, senhor. "
    "Falta a chave. Rode python -m jarvis.setup."
)
JIRA_FAIL = "Não consegui consultar o Jira, senhor."
GITHUB_MISSING = "O GitHub não está autenticado, senhor. Rode gh auth login."
GITHUB_FAIL = "Não consegui consultar os PRs, senhor."
MAIL_MISSING = (
    "O e-mail não está configurado, senhor. "
    "Falta a senha de app. Rode python -m jarvis.setup."
)
MAIL_FAIL = "Não consegui ler o e-mail, senhor."

_DONE = {"done", "concluido", "concluida", "resolvido", "resolvida", "fechado", "fechada"}
_PROGRESS = {"indeterminate", "em andamento", "in progress", "fazendo"}
_TODO = {"new", "a fazer", "to do", "backlog", "aberto", "aberta", "pendente"}


def handle(kind):
    if kind == "jira":
        return jira_speech()
    if kind == "github":
        return github_speech()
    if kind == "mail":
        return mail_speech()
    return ""


def jira_briefing():
    return jira_speech(briefing=True, limit=3)


def github_briefing():
    return github_speech(briefing=True, limit=3)


def jira_config():
    base = config.jira_url()
    email = config.jira_email()
    token = config.jira_token()
    if not base or not email or not token:
        return None
    if "://" not in base:
        return None
    return base, email, token


def jira_speech(briefing=False, limit=8, opener=None):
    issues = jira_issues(limit=limit, opener=opener)
    if issues is None:
        return "" if briefing else JIRA_MISSING
    if issues is False:
        return JIRA_FAIL
    progress = [item["label"] for item in issues if item["bucket"] == "progress"]
    todo = [item["label"] for item in issues if item["bucket"] == "todo"]
    other = [item["label"] for item in issues if item["bucket"] == "other"]
    if not progress and not todo and not other:
        if briefing:
            return "No Jira, nada em aberto."
        return "Não há issue aberta no Jira, senhor."
    sentence = _jira_sentence(progress, todo, other)
    if briefing:
        return "Jira, " + sentence
    return "No Jira, " + sentence


def jira_issues(limit=8, opener=None):
    """None sem configuração, False se a consulta falhar, senão a lista. Só GET."""
    config = jira_config()
    if config is None:
        return None
    base, email, token = config
    query = urllib.parse.urlencode(
        {
            "jql": "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC",
            "maxResults": str(limit),
            "fields": "summary,status",
        }
    )
    url = base + "/rest/api/3/search/jql?" + query
    request = urllib.request.Request(url)
    raw = base64.b64encode(f"{email}:{token}".encode()).decode("ascii")
    request.add_header("Authorization", "Basic " + raw)
    request.add_header("Accept", "application/json")
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        LOG.error("jira: consulta falhou")
        return False
    if not isinstance(payload, dict):
        LOG.error("jira: resposta inesperada")
        return False
    return _jira_records(payload.get("issues") or [], limit)


def _jira_records(issues, limit):
    found = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        fields = issue.get("fields") or {}
        status = fields.get("status") or {}
        category = status.get("statusCategory") or {}
        key_name = str(category.get("key") or status.get("name") or "")
        folded = key_name.casefold()
        if folded in _DONE:
            continue
        label = str(issue.get("key") or "").strip()
        summary = " ".join(str(fields.get("summary") or "").split())
        if not label and not summary:
            continue
        if folded in _PROGRESS:
            bucket = "progress"
        elif folded in _TODO:
            bucket = "todo"
        else:
            bucket = "other"
        found.append({"label": (label + " " + summary).strip(), "bucket": bucket})
        if len(found) >= limit:
            break
    return found


def _jira_sentence(progress, todo, other):
    parts = []
    if progress:
        parts.append("em andamento: " + _list(progress))
    if todo:
        parts.append("a fazer: " + _list(todo))
    if other:
        parts.append("também: " + _list(other))
    return ". ".join(parts) + "."


def github_pulls(limit=8):
    """None sem gh autenticado, False se a consulta falhar. Só search, sem comentar."""
    if not github_ready():
        return None
    opened = _search_prs("author=@me", limit)
    reviews = _search_prs("review-requested=@me", limit)
    if opened is None or reviews is None:
        return False
    return {"opened": opened, "reviews": reviews}


def github_speech(briefing=False, limit=8):
    pulls = github_pulls(limit=limit)
    if pulls is None:
        return "" if briefing else GITHUB_MISSING
    if pulls is False:
        return GITHUB_FAIL
    opened = pulls["opened"]
    reviews = pulls["reviews"]
    if not opened and not reviews:
        if briefing:
            return "Nos PRs, nada em aberto."
        return "Não há PR aberto nem review pendente, senhor."
    parts = []
    if opened:
        parts.append("PRs abertos: " + _list(opened))
    if reviews:
        parts.append("Reviews pendentes: " + _list(reviews))
    sentence = ". ".join(parts) + "."
    if briefing:
        return sentence
    return "Senhor, " + sentence


def github_ready():
    return github_auth_state() == "ok"


def github_auth_state():
    binary = _gh_binary()
    if binary is None:
        return "missing"
    process = _run_tool(binary, ["auth", "status"], 20)
    if process is None:
        return "error"
    if process.returncode == 0:
        return "ok"
    return "anonymous"


def _search_prs(qualifier, limit):
    result = _gh(
        [
            "search",
            "prs",
            "--" + qualifier,
            "--state=open",
            "--limit=" + str(limit),
            "--json=number,title,repository,url",
        ]
    )
    if result is None:
        return None
    try:
        payload = json.loads(result or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    lines = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        repo = item.get("repository")
        if isinstance(repo, dict):
            name = repo.get("nameWithOwner") or repo.get("name") or "repositório"
        else:
            name = repo or "repositório"
        number = item.get("number")
        title = " ".join(str(item.get("title") or "").split())
        label = f"{name} {number}".strip()
        if title:
            label = f"{label}, {title}"
        lines.append(label)
    return lines


def _gh_binary():
    binary = config.gh_bin()
    if os.path.sep not in binary and shutil.which(binary) is None:
        return None
    if os.path.sep in binary and not os.path.isfile(binary):
        return None
    return binary


def _run_tool(binary, args, timeout):
    from .procutil import command_argv

    argv = command_argv(binary, *args)
    if not argv:
        return None
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _gh(args):
    binary = _gh_binary()
    if binary is None:
        return None
    process = _run_tool(binary, args, 20)
    if process is None:
        LOG.error("github: consulta falhou")
        return None
    if process.returncode != 0:
        return None
    return process.stdout


def mail_config():
    user = config.gmail_email()
    password = config.gmail_password()
    host = config.gmail_host()
    port = config.gmail_port()
    if not user or not password:
        return None
    return host, port, user, password


def mail_briefing(connect=None):
    return _mail_report(connect, briefing=True)


def mail_speech(connect=None):
    return _mail_report(connect, briefing=False)


def _mail_report(connect, briefing):
    """Só leitura da caixa de entrada. Não envia e não marca como lido."""

    config = mail_config()
    if config is None:
        return "" if briefing else MAIL_MISSING
    host, port, user, password = config
    opener = connect or _imap_connect
    try:
        imap = opener(host, port)
    except Exception:
        LOG.error("e-mail: conexão falhou")
        return MAIL_FAIL
    try:
        imap.login(user, password)
        messages = _unread(imap)
    except Exception:
        LOG.error("e-mail: leitura falhou")
        return MAIL_FAIL
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    if not messages:
        if briefing:
            return "No e-mail, nada não lido."
        return "Não há e-mail não lido, senhor."
    shown = messages[:5]
    extra = len(messages) - len(shown)
    if briefing:
        titles = [_spoken(item["subject"], 80) for item in shown]
        sentence = f"E-mail, {len(messages)} não lidos: " + _list(titles)
        if extra:
            sentence += f". E mais {extra}"
        return sentence + "."
    bits = [f"De {_spoken(item['from'], 60)}: {_spoken(item['subject'], 80)}" for item in shown]
    sentence = f"Há {len(messages)} não lidos, senhor. " + ". ".join(bits)
    if extra:
        sentence += f". E mais {extra}"
    return sentence + "."


def _imap_connect(host, port):
    import imaplib

    return imaplib.IMAP4_SSL(host, port, timeout=15)


def _unread(imap):
    imap.select("INBOX", readonly=True)
    status, data = imap.search(None, "UNSEEN")
    if status != "OK":
        raise RuntimeError("busca")
    numbers = (data[0] or b"").split() if data else []
    messages = []
    for number in numbers[:20]:
        status, fetched = imap.fetch(number, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
        if status != "OK":
            continue
        header = _header_blob(fetched)
        parsed = Parser().parsestr(header)
        messages.append(
            {
                "from": _decode_header(parsed.get("From") or "remetente desconhecido"),
                "subject": _decode_header(parsed.get("Subject") or "sem assunto"),
            }
        )
    return messages


def _header_blob(fetched):
    chunks = []
    for item in fetched or []:
        parts = item if isinstance(item, tuple) else (item,)
        for part in parts:
            if isinstance(part, bytes) and (b"Subject:" in part or b"From:" in part):
                chunks.append(part.decode("utf-8", "replace"))
    return "\n".join(chunks)


def _decode_header(value):
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value or "")


def _list(items):
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " e " + items[-1]


def _spoken(text, limit):
    cleaned = " ".join(
        str(text or "").replace("<", " ").replace(">", " ").replace("\u2014", " ").replace("\u2013", " ").split()
    )
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def github_review_sample(limit=8):
    """PRs do usuário com review pedido. off, ok ou error. Só leitura."""
    state = github_auth_state()
    if state in {"missing", "anonymous"}:
        return "off", []
    if state != "ok":
        return "error", []
    result = _gh(
        [
            "search",
            "prs",
            "--author=@me",
            "--state=open",
            "--limit=" + str(limit),
            "--json=number,title,repository,url",
        ]
    )
    if result is None:
        return "error", []
    try:
        payload = json.loads(result or "[]")
    except json.JSONDecodeError:
        return "error", []
    if not isinstance(payload, list):
        return "error", []
    items = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        repo = _repo_name(item.get("repository"))
        number = item.get("number")
        if not repo or not number:
            continue
        detail = _gh(
            [
                "pr",
                "view",
                str(number),
                "--repo",
                repo,
                "--json=reviewRequests,title",
            ]
        )
        if detail is None:
            return "error", []
        try:
            viewed = json.loads(detail or "{}")
        except json.JSONDecodeError:
            return "error", []
        if not isinstance(viewed, dict):
            return "error", []
        requests = viewed.get("reviewRequests") or []
        if not isinstance(requests, list) or not requests:
            continue
        title = " ".join(str(viewed.get("title") or item.get("title") or "").split())
        label = _spoken(f"{repo} {number}, {title}".strip(" ,"), 120)
        items.append({"id": f"{repo}#{number}", "label": label})
    return "ok", items


def _repo_name(repository):
    if isinstance(repository, dict):
        name = repository.get("nameWithOwner") or ""
        if not name and repository.get("name"):
            owner = repository.get("owner") or {}
            login = owner.get("login") if isinstance(owner, dict) else ""
            name = (str(login) + "/" + str(repository.get("name"))).strip("/")
        return str(name or "").strip()
    return str(repository or "").strip()


def jira_status_sample(opener=None, limit=15):
    """Issues recentes e o status atual. off, ok ou error. Só GET."""
    config = jira_config()
    if config is None:
        return "off", []
    base, email, token = config
    query = urllib.parse.urlencode(
        {
            "jql": "assignee = currentUser() ORDER BY updated DESC",
            "maxResults": str(limit),
            "fields": "summary,status",
        }
    )
    url = base + "/rest/api/3/search/jql?" + query
    request = urllib.request.Request(url, method="GET")
    raw = base64.b64encode(f"{email}:{token}".encode()).decode("ascii")
    request.add_header("Authorization", "Basic " + raw)
    request.add_header("Accept", "application/json")
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        LOG.error("jira: consulta de status falhou")
        return "error", []
    if not isinstance(payload, dict):
        return "error", []
    items = []
    for issue in payload.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        key = str(issue.get("key") or "").strip()
        fields = issue.get("fields") or {}
        status = fields.get("status") or {}
        name = " ".join(str(status.get("name") or "").split())
        summary = _spoken(fields.get("summary") or "", 80)
        if not key or not name:
            continue
        items.append({"key": key, "status": name, "summary": summary})
        if len(items) >= limit:
            break
    return "ok", items


def important_mail_sample(connect=None, limit=8):
    """E-mails importantes não lidos. off, ok ou error. Não marca como lido."""
    config = mail_config()
    if config is None:
        return "off", []
    host, port, user, password = config
    opener = connect or _imap_connect
    try:
        imap = opener(host, port)
    except Exception:
        LOG.error("e-mail: conexão do alerta falhou")
        return "error", []
    try:
        imap.login(user, password)
        imap.select("INBOX", readonly=True)
        status, data = imap.search(None, "X-GM-RAW", "is:important is:unread")
        if status != "OK":
            raise RuntimeError("busca")
        numbers = (data[0] or b"").split() if data else []
        items = []
        for number in numbers[:limit]:
            status, fetched = imap.fetch(
                number, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
            )
            if status != "OK":
                continue
            header = _header_blob(fetched)
            parsed = Parser().parsestr(header)
            sender = _spoken(_decode_header(parsed.get("From") or ""), 60) or "remetente"
            subject = _spoken(_decode_header(parsed.get("Subject") or ""), 80) or "sem assunto"
            date = " ".join(_decode_header(parsed.get("Date") or "").split())
            items.append(
                {
                    "id": _mail_id(sender, subject, date),
                    "sender": sender,
                    "subject": subject,
                }
            )
    except Exception:
        LOG.error("e-mail: alerta falhou")
        return "error", []
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return "ok", items


def _mail_id(sender, subject, date):
    raw = "\n".join([sender, subject, date]).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]
