"""Executa cliente e servidor reais em localhost para validar o protocolo CP3."""

import socket
import subprocess
import sys
import threading
import time
import unittest


MENSAGEM_JANELA_5 = "abcdefghijklmnopqrst"
MENSAGEM_UTF8 = "áéíóXYZ🙂a"
MENSAGEM_DUAS_JANELAS = "abcdefghijklmnopqrstuvwxYz"


def escolher_porta_livre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def cenarios():
    return [
        ("GBN W5 sem falhas", "1", 5, MENSAGEM_JANELA_5, (), ()),
        ("GBN W5 corrupção", "1", 5, MENSAGEM_JANELA_5, (2,), ()),
        ("GBN W5 perda", "1", 5, MENSAGEM_JANELA_5, (), (2,)),
        ("GBN W5 corrupção e perda", "1", 5, MENSAGEM_JANELA_5, (2,), (4,)),
        ("SR W5 sem falhas", "2", 5, MENSAGEM_JANELA_5, (), ()),
        ("SR W5 corrupção", "2", 5, MENSAGEM_JANELA_5, (2,), ()),
        ("SR W5 perda", "2", 5, MENSAGEM_JANELA_5, (), (2,)),
        ("SR W5 corrupção e perda", "2", 5, MENSAGEM_JANELA_5, (2,), (4,)),
        ("GBN W1 sem falhas", "1", 1, "abcdefghijk", (), ()),
        ("SR W1 sem falhas", "2", 1, "abcdefghijk", (), ()),
        ("GBN UTF-8 e fragmento curto", "1", 5, MENSAGEM_UTF8, (), ()),
        ("SR UTF-8 e fragmento curto", "2", 5, MENSAGEM_UTF8, (), ()),
        ("GBN W1 corrupção", "1", 1, MENSAGEM_JANELA_5, (2,), ()),
        ("GBN W1 perda", "1", 1, MENSAGEM_JANELA_5, (), (2,)),
        ("SR W1 corrupção", "2", 1, MENSAGEM_JANELA_5, (2,), ()),
        ("SR W1 perda", "2", 1, MENSAGEM_JANELA_5, (), (2,)),
        ("GBN W5 duas janelas", "1", 5, MENSAGEM_DUAS_JANELAS, (), ()),
        ("SR W5 duas janelas", "2", 5, MENSAGEM_DUAS_JANELAS, (), ()),
        ("GBN corrupção na segunda janela", "1", 5, MENSAGEM_DUAS_JANELAS, (6,), ()),
        ("SR perda na segunda janela", "2", 5, MENSAGEM_DUAS_JANELAS, (), (6,)),
    ]


class Checkpoint3IntegrationTests(unittest.TestCase):
    def test_matriz_cliente_servidor_em_processos_separados(self):
        porta = escolher_porta_livre()
        server_code = (
            f"import server; server.SERVER_PORT = {porta}; server.start_server()"
        )
        server = subprocess.Popen(
            [sys.executable, "-u", "-c", server_code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        logs_servidor = []

        def ler_logs_servidor():
            logs_servidor.extend(server.stdout.readlines())

        leitor = threading.Thread(target=ler_logs_servidor, daemon=True)
        leitor.start()
        saidas_cliente = []

        try:
            servidor_pronto = False
            for _ in range(60):
                if server.poll() is not None:
                    self.fail("O processo do servidor encerrou antes dos testes.")
                try:
                    with socket.create_connection(("127.0.0.1", porta), timeout=0.2):
                        servidor_pronto = True
                        break
                except OSError:
                    time.sleep(0.1)
            self.assertTrue(servidor_pronto, "O servidor não abriu a porta de teste.")

            for nome, modo, janela, texto, corromper, perder in cenarios():
                server.stdin.write(f"{janela}\n")
                server.stdin.flush()
                client_code = (
                    f"import cliente; cliente.SERVER_PORT = {porta}; "
                    "cliente.iniciar_cliente()"
                )
                cliente = subprocess.Popen(
                    [sys.executable, "-u", "-c", client_code],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                )

                respostas = [modo, "30", texto]
                if not corromper and not perder:
                    respostas.append("n")
                else:
                    respostas.extend(
                        [
                            "s",
                            ",".join(map(str, corromper)),
                            ",".join(map(str, perder)),
                        ]
                    )
                saida, _ = cliente.communicate(
                    "\n".join(respostas) + "\n", timeout=25
                )
                saidas_cliente.append(saida)
                self.assertEqual(cliente.returncode, 0, f"{nome}: cliente encerrou com erro")
                self.assertIn(
                    "Mensagem concluída pelo servidor",
                    saida,
                    f"{nome}: transferência não terminou corretamente\n{saida[-2000:]}",
                )

                if corromper:
                    self.assertIn("NACK", saida, f"{nome}: corrupção sem NACK")
                if perder and modo == "1":
                    self.assertIn("NACK da janela", saida, f"{nome}: GBN sem recuperação")
                if perder and modo == "2":
                    self.assertIn("Timeout individual", saida, f"{nome}: SR sem timeout")
                if corromper and perder and modo == "2":
                    self.assertIn("NACK individual | SEQ=2", saida)
                    self.assertIn("Timeout individual | SEQ=4", saida)

        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
            if server.stdin and not server.stdin.closed:
                server.stdin.close()
            leitor.join(timeout=5)
            server.stdout.close()

        texto_servidor = "".join(logs_servidor)
        casos = cenarios()
        self.assertEqual(
            texto_servidor.count("Mensagem completa recebida:"),
            len(casos),
            "O servidor não concluiu todas as sessões.",
        )
        for texto in {caso[3] for caso in casos}:
            esperado = sum(1 for caso in casos if caso[3] == texto)
            self.assertEqual(
                texto_servidor.count(f"\n{texto}\n"),
                esperado,
                f"O servidor não remontou corretamente {texto!r}.",
            )
        self.assertIn("DATA fora de ordem", texto_servidor)
        self.assertIn("CRC=OK | cifra=OK", texto_servidor)


if __name__ == "__main__":
    unittest.main()
