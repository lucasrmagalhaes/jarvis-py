import json
import os
import subprocess
import sys
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis import doctor
from jarvis.consult import (
    MODEL_NAME,
    PROBE,
    answer,
    download_model,
    open_model,
    pick_lan_host,
    reset_libraries,
    resolve_bind,
)
from jarvis.consult import LocalModel
from jarvis.consult_http import Limiter, serve
from jarvis.routines import fold, search_notes

TOKEN = "token-de-teste-123456"
HORTA = (
    "# Caixa da janela\n\n"
    "A hortelã da caixa cresce na janela da cozinha de teste e segue firme no vaso claro.\n"
    "Veja [[Porto ficticio]].\n"
)
PORTO = (
    "# Porto ficticio\n\n"
    "O farol de teste marca a entrada do porto ficticio com luz amarela e constante.\n"
)
AROMAS = (
    "# Laboratorio ficticio\n\n"
    "O cultivo de folhas aromaticas fica na caixa azul do laboratorio ficticio de teste.\n"
)
OUTSIDE = (
    "# Fora\n\n"
    "O segredo externo do cofre oculto fica somente neste arquivo vizinho de teste.\n"
)
PLUGIN = (
    "# Plugin\n\n"
    "O marcador oculto do plugin secreto aparece somente aqui dentro da pasta local.\n"
)


def snapshot(root):
    found = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


def make_vault(root):
    root.mkdir()
    (root / "caixa.md").write_text(HORTA, encoding="utf-8")
    (root / "porto.md").write_text(PORTO, encoding="utf-8")
    hidden = root / ".obsidian"
    hidden.mkdir()
    (hidden / "plugin.md").write_text(PLUGIN, encoding="utf-8")
    return root


class ConsultRetrievalTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        reset_libraries()
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "vault"
        self.addCleanup(reset_libraries)
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def test_vector_hits_when_textual_search_misses_a_word(self):
        make_vault(self.root)
        before = snapshot(self.root)
        query = "horteloes cultivados na caixa da janela"
        self.assertEqual(search_notes(self.root, query), [])
        result = answer(self.root, query, embedder=None)
        self.assertTrue(result["evidence"])
        self.assertEqual(result["mode"], "vetorial")
        self.assertTrue(result["read_only"])
        self.assertFalse(result["persisted"])
        self.assertEqual(result["sources"][0]["path"], "caixa.md")
        self.assertIn("hortel", result["sources"][0]["excerpt"].casefold())
        self.assertIn("caixa.md", result["answer"])
        self.assertIn("sem evidência", result["answer"])
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertTrue(result["sources"][0]["obsidian"].startswith("obsidian://"))
        self.assertNotIn(str(self.root), result["sources"][0]["obsidian"])
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / ".git").exists())

    def test_natural_question_stays_inside_the_note(self):
        make_vault(self.root)
        result = answer(self.root, "o que eu escrevi sobre hortela da janela", embedder=None)
        self.assertTrue(result["evidence"])
        self.assertEqual(result["sources"][0]["path"], "caixa.md")
        self.assertIn("[[caixa]]", result["sources"][0]["wikilink"])

    def test_missing_evidence_is_declared_and_not_written(self):
        make_vault(self.root)
        before = snapshot(self.root)
        result = answer(self.root, "receita de bolo de chocolate", embedder=None)
        self.assertFalse(result["evidence"])
        self.assertEqual(result["mode"], "nenhuma")
        self.assertEqual(result["sources"], [])
        self.assertIn("Não há evidência", result["answer"])
        self.assertEqual(result["suggestions"]["flashcards"], [])
        self.assertEqual(snapshot(self.root), before)

    def test_textual_fallback_when_vector_score_is_rejected(self):
        make_vault(self.root)
        result = answer(self.root, "farol teste porto", embedder=None, vector_min=9)
        self.assertTrue(result["evidence"])
        self.assertIn(result["mode"], {"palavra", "textual", "hibrida"})
        self.assertEqual(result["sources"][0]["path"], "porto.md")
        self.assertIn("farol", result["answer"].casefold())

    def test_suggestions_do_not_mutate_the_vault(self):
        make_vault(self.root)
        before = snapshot(self.root)
        result = answer(self.root, "hortela da caixa na janela", embedder=None)
        self.assertTrue(result["evidence"])
        cards = result["suggestions"]["flashcards"]
        links = result["suggestions"]["connections"]
        self.assertFalse(result["suggestions"]["persisted"])
        self.assertTrue(cards)
        self.assertTrue(all(card["persisted"] is False for card in cards))
        self.assertTrue(any(link["target"] == "porto.md" for link in links))
        self.assertTrue(all(link["persisted"] is False for link in links))
        self.assertEqual(snapshot(self.root), before)

    def test_symlink_and_obsidian_stay_out_of_the_answer(self):
        make_vault(self.root)
        outside = self.root.parent / "fora.md"
        outside.write_text(OUTSIDE, encoding="utf-8")
        try:
            (self.root / "ponte.md").symlink_to(outside)
        except OSError:
            self.skipTest("sem symlink")
        result = answer(self.root, "segredo externo cofre oculto", embedder=None)
        plugin = answer(self.root, "marcador oculto plugin secreto", embedder=None)
        blob = json.dumps(
            {"answer": result["answer"], "sources": result["sources"], "nearby": result["nearby"]}
        ) + json.dumps(
            {"answer": plugin["answer"], "sources": plugin["sources"], "nearby": plugin["nearby"]}
        )
        self.assertNotIn("arquivo vizinho", blob)
        self.assertNotIn("aparece somente aqui dentro", blob)
        self.assertFalse(result["evidence"])
        self.assertFalse(plugin["evidence"])
        outside.unlink()

    def test_other_folder_is_not_searched(self):
        make_vault(self.root)
        other = self.root.parent / "outro"
        if other.exists():
            import shutil
            shutil.rmtree(other)
        other.mkdir()
        (other / "solo.md").write_text(
            "# Solo\n\n"
            "O cristal zafiro exclusivo aparece somente neste outro caderno ficticio de teste.\n",
            encoding="utf-8",
        )
        quiet = answer(self.root, "cristal zafiro exclusivo", embedder=None)
        found = answer(other, "cristal zafiro exclusivo", embedder=None)
        self.assertFalse(quiet["evidence"])
        self.assertTrue(found["evidence"])
        self.assertEqual(found["sources"][0]["path"], "solo.md")
        import shutil
        shutil.rmtree(other)

    def test_markup_in_a_note_is_not_returned_as_markup(self):
        self.root.mkdir()
        (self.root / "segura.md").write_text(
            "# Segura\n\n"
            "<script>alert(1)</script> o farol seguro aparece no texto deste caderno ficticio.\n",
            encoding="utf-8",
        )
        result = answer(self.root, "farol seguro", embedder=None)
        blob = json.dumps(result)
        self.assertNotIn("<", blob)
        self.assertNotIn(">", blob)
        self.assertTrue(result["evidence"])

    def test_local_model_can_rank_without_shared_words(self):
        self.root.mkdir()
        (self.root / "aromas.md").write_text(AROMAS, encoding="utf-8")
        (self.root / "porto.md").write_text(PORTO, encoding="utf-8")

        class Stub:
            def embed(self, texts):
                rows = []
                for text in texts:
                    folded = fold(text)
                    if "aromatic" in folded or "varanda" in folded:
                        rows.append([1.0, 0.0])
                    else:
                        rows.append([0.0, 1.0])
                return rows

        result = answer(self.root, "ervas na varanda do predio", embedder=Stub())
        self.assertTrue(result["evidence"])
        self.assertEqual(result["mode"], "modelo")
        self.assertEqual(result["sources"][0]["path"], "aromas.md")
        self.assertNotIn("porto.md", [item["path"] for item in result["sources"]])

    def test_model_failure_falls_back_and_hides_the_error(self):
        make_vault(self.root)

        class Boom:
            def embed(self, texts):
                raise RuntimeError("segredo interno")

        result = answer(self.root, "hortela da caixa na janela", embedder=Boom())
        self.assertTrue(result["evidence"])
        self.assertIn(result["mode"], {"vetorial", "hibrida", "palavra"})
        self.assertNotIn("segredo interno", json.dumps(result))

    def test_weak_model_does_not_invent_evidence(self):
        self.root.mkdir()
        (self.root / "aromas.md").write_text(AROMAS, encoding="utf-8")

        class Low:
            def __init__(self):
                self.calls = 0

            def embed(self, texts):
                self.calls += 1
                if self.calls == 1:
                    return [[0.0, 1.0] for _ in texts]
                return [[1.0, 0.0] for _ in texts]

        result = answer(self.root, "ervas na varanda do predio", embedder=Low())
        self.assertFalse(result["evidence"])
        self.assertEqual(result["sources"], [])


class ConsultModelFilesTest(unittest.TestCase):
    def test_query_loader_asks_for_local_files_only(self):
        seen = {}

        class Fake:
            def __init__(self, **kwargs):
                seen.update(kwargs)

        self.assertIsNotNone(open_model(Path("cache"), True, loader=lambda: Fake))
        self.assertTrue(seen["local_files_only"])
        self.assertEqual(seen["model_name"], MODEL_NAME)

    def test_old_loader_cannot_download_during_a_query(self):
        class Old:
            def __init__(self, model_name=None, cache_dir=None, local_files_only=None):
                if local_files_only is not None:
                    raise TypeError("antiga")
                raise AssertionError("download")

        self.assertIsNone(open_model(Path("cache"), True, loader=lambda: Old))

    def test_embed_uses_offline_flag_and_skips_missing_weights(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            opened = {}

            def opener(path, local_only):
                opened["called"] = True
                return None

            self.assertIsNone(LocalModel(cache, opener=opener).embed(["texto"]))
            self.assertNotIn("called", opened)
            (cache / "model.onnx").write_bytes(b"pesos")

            def open_real(path, local_only):
                opened["local"] = local_only
                opened["offline"] = os.environ.get("HF_HUB_OFFLINE")

                class Model:
                    def embed(self, texts):
                        opened["texts"] = list(texts)
                        return [[0.2, 0.4] for _ in texts]

                return Model()

            previous = os.environ.pop("HF_HUB_OFFLINE", None)
            try:
                rows = LocalModel(cache, opener=open_real).embed(["texto local"])
            finally:
                if previous is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = previous
            self.assertEqual(rows, [[0.2, 0.4]])
            self.assertTrue(opened["local"])
            self.assertEqual(opened["offline"], "1")
            self.assertIsNone(os.environ.get("HF_HUB_OFFLINE"))
            self.assertEqual(opened["texts"], ["texto local"])

    def test_download_does_not_read_the_vault(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            (vault / "segredo.md").write_text("frase secreta do caderno\n", encoding="utf-8")
            previous = os.environ.get("JARVIS_VAULT")
            os.environ["JARVIS_VAULT"] = str(vault)
            seen = {}

            def opener(path, local_only):
                seen["local"] = local_only
                seen["probe"] = PROBE
                return object()

            try:
                code, message = download_model(Path(tmp) / "modelo", opener=opener)
            finally:
                if previous is None:
                    os.environ.pop("JARVIS_VAULT", None)
                else:
                    os.environ["JARVIS_VAULT"] = previous
            self.assertEqual(code, 0)
            self.assertFalse(seen["local"])
            self.assertNotIn("frase secreta", message)
            self.assertNotIn("frase secreta", str(seen))


class ConsultBindTest(unittest.TestCase):
    def test_public_and_unspecified_addresses_are_refused(self):
        self.assertEqual(resolve_bind("127.0.0.1"), "127.0.0.1")
        self.assertEqual(resolve_bind(""), "127.0.0.1")
        self.assertEqual(resolve_bind("::1"), "::1")
        self.assertEqual(resolve_bind("192.168.1.20"), "192.168.1.20")
        self.assertEqual(resolve_bind("10.1.2.3"), "10.1.2.3")
        self.assertEqual(resolve_bind("172.16.5.5"), "172.16.5.5")
        self.assertIsNone(resolve_bind("0.0.0.0"))
        self.assertIsNone(resolve_bind("::"))
        self.assertIsNone(resolve_bind("8.8.8.8"))
        self.assertIsNone(resolve_bind("172.32.5.5"))
        self.assertIsNone(resolve_bind("169.254.1.1"))
        self.assertIsNone(resolve_bind("localhost"))
        self.assertIsNone(resolve_bind("lan"))

    def test_lan_picker_ignores_public_addresses(self):
        import socket

        def fake_info(*args, **kwargs):
            return [(socket.AF_INET, None, None, "", ("8.8.8.8", 0))]

        with mock.patch("jarvis.consult.socket.getaddrinfo", fake_info):
            with mock.patch("jarvis.consult.socket.socket") as factory:
                factory.side_effect = OSError("sem rota")
                self.assertIsNone(pick_lan_host())


class ConsultHttpTest(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile

        reset_libraries()
        self.tmp = Path(tempfile.mkdtemp())
        self.root = make_vault(self.tmp / "vault")
        self.server = serve(self.root, TOKEN, "127.0.0.1", 0, embedder=None)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.addCleanup(reset_libraries)

    def request(self, method, path, body=None, headers=None):
        last = None
        for _ in range(20):
            conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
            data = None
            hdrs = dict(headers or {})
            if body is not None:
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                hdrs.setdefault("Content-Type", "application/json")
                hdrs["Content-Length"] = str(len(data))
            try:
                conn.request(method, path, body=data, headers=hdrs)
                response = conn.getresponse()
                payload = response.read()
                headers_out = response.getheaders()
                status = response.status
                conn.close()
                return status, headers_out, payload
            except (ConnectionRefusedError, OSError) as error:
                last = error
                conn.close()
                import time
                time.sleep(0.05)
        raise last

    def auth(self, **extra):
        headers = {
            "Cookie": "jarvis_consult=" + TOKEN,
            "X-Jarvis-Consult": "1",
            "Origin": "http://127.0.0.1",
        }
        headers.update(extra)
        return headers

    def test_entry_sets_a_cookie_and_the_page_has_no_secret(self):
        status, headers, body = self.request("GET", "/entrar?t=" + TOKEN)
        joined = " ".join(value for name, value in headers if name.lower() == "set-cookie")
        text = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", joined)
        self.assertIn("SameSite=Strict", joined)
        self.assertIn("Secure", joined)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn("hortel", text.casefold())
        cache = " ".join(value for name, value in headers if name.lower() == "cache-control")
        self.assertIn("no-store", cache)
        denied, _, _ = self.request("GET", "/entrar?t=outro-token-diferente")
        self.assertEqual(denied, 403)

    def test_consult_requires_cookie_header_and_host(self):
        before = snapshot(self.root)
        ok, headers, body = self.request(
            "POST",
            "/consultar",
            {"q": "horteloes cultivados na caixa da janela"},
            self.auth(),
        )
        self.assertEqual(ok, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertTrue(payload["evidence"])
        self.assertEqual(payload["sources"][0]["path"], "caixa.md")
        self.assertNotIn(str(self.root), body.decode("utf-8"))
        cache = " ".join(value for name, value in headers if name.lower() == "cache-control")
        self.assertIn("no-store", cache)
        missing, _, _ = self.request(
            "POST",
            "/consultar",
            {"q": "hortela"},
            {"X-Jarvis-Consult": "1", "Origin": "http://127.0.0.1"},
        )
        self.assertEqual(missing, 403)
        foreign, _, _ = self.request(
            "POST",
            "/consultar",
            {"q": "hortela"},
            self.auth(Origin="http://evil.example"),
        )
        self.assertEqual(foreign, 403)
        rebound, _, _ = self.request("GET", "/", headers={"Host": "evil.example"})
        self.assertEqual(rebound, 403)
        self.assertEqual(snapshot(self.root), before)

    def test_shell_is_network_only_and_refuses_writes(self):
        status, _, body = self.request("GET", "/sw.js")
        script = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("no-store", script)
        self.assertIn("caches.delete", script)
        self.assertNotIn("cache.put", script)
        self.assertNotIn("addAll", script)
        manifest_status, _, manifest = self.request("GET", "/manifest.webmanifest")
        self.assertEqual(manifest_status, 200)
        self.assertEqual(json.loads(manifest.decode("utf-8"))["start_url"], "/")
        blocked, _, _ = self.request("PUT", "/consultar", {"q": "hortela"}, self.auth())
        self.assertEqual(blocked, 405)
        removed, _, _ = self.request("DELETE", "/caixa.md", headers=self.auth())
        self.assertEqual(removed, 405)
        self.assertTrue((self.root / "caixa.md").is_file())

    def test_rate_limit_and_large_body(self):
        limited = serve(
            self.root,
            TOKEN,
            "127.0.0.1",
            0,
            embedder=None,
            limiter=Limiter(limit=1, window=60, clock=lambda: 100),
        )
        port = limited.server_address[1]
        thread = threading.Thread(target=limited.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(limited.shutdown)
        self.addCleanup(limited.server_close)
        saved = self.port
        self.port = port
        try:
            first, _, _ = self.request("POST", "/consultar", {"q": "farol teste porto"}, self.auth())
            second, _, _ = self.request("POST", "/consultar", {"q": "farol teste porto"}, self.auth())
        finally:
            self.port = saved
        self.assertEqual(first, 200)
        self.assertEqual(second, 429)
        huge, _, _ = self.request(
            "POST",
            "/consultar",
            b"{" + b" " * 9000,
            self.auth(),
        )
        self.assertEqual(huge, 413)


class ConsultCommandTest(unittest.TestCase):
    def test_help_and_missing_vault(self):
        import tempfile

        home = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(home, ignore_errors=True))
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": home,
            "LANG": "C.UTF-8",
        }
        help_run = subprocess.run(
            [sys.executable, "-m", "jarvis.consult", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(help_run.returncode, 0)
        self.assertIn("somente leitura", help_run.stdout)
        bare = subprocess.run(
            [sys.executable, "-m", "jarvis.consult"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(bare.returncode, 1)
        self.assertIn("JARVIS_VAULT", bare.stdout)
        self.assertNotIn("hortel", bare.stdout.casefold())

    def test_lan_without_a_private_address_does_not_listen(self):
        import tempfile

        from jarvis.consult import main

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            make_vault(vault)
            previous = {
                key: os.environ.get(key)
                for key in ("JARVIS_VAULT", "JARVIS_CONSULT_BIND")
            }
            os.environ["JARVIS_VAULT"] = str(vault)
            os.environ["JARVIS_CONSULT_BIND"] = "lan"
            try:
                with mock.patch("jarvis.consult.pick_lan_host", return_value=None):
                    with mock.patch("sys.stdout"):
                        code = main([])
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            self.assertEqual(code, 1)

    def test_doctor_mentions_the_local_command(self):
        import contextlib
        import io

        doctor.results.clear()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            doctor.check_consult()
        text = buffer.getvalue()
        self.assertTrue("jarvis.consult" in text or "JARVIS_CONSULT_PORT" in text)
        self.assertIn("127.0.0.1", text)

    def test_sources_have_no_dash_and_no_note_cache(self):
        files = [
            "jarvis/consult.py",
            "jarvis/consult_http.py",
            "jarvis/static/consult/index.html",
            "jarvis/static/consult/app.js",
            "jarvis/static/consult/app.css",
            "jarvis/static/consult/sw.js",
            "jarvis/static/consult/manifest.webmanifest",
            "requirements-consult.txt",
            "mapa/Consulta Android.md",
        ]
        for name in files:
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("\u2014", text, name)
            self.assertNotIn("\u2013", text, name)
        module = (ROOT / "jarvis/consult.py").read_text(encoding="utf-8")
        page = (ROOT / "jarvis/static/consult/app.js").read_text(encoding="utf-8")
        self.assertNotIn("write_text", module)
        self.assertNotIn("sounddevice", module)
        self.assertNotIn("subprocess", module)
        self.assertNotIn("urlopen", module)
        self.assertNotIn("innerHTML", page)
        self.assertNotIn("localStorage", page)
        self.assertNotIn("indexedDB", page)
        self.assertNotIn("sessionStorage", page)


if __name__ == "__main__":
    unittest.main()
