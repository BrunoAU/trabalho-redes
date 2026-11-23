import unittest
import socket
import threading

from checksum import crc16_ibm_3740
from cipher import cifrar, decifrar
from cliente import corromper_pacote, dividir_mensagem, montar_pacote, enviar, receber
from server import (
    FrameError,
    parsear_pacote,
    receber_repeticao_seletiva,
)


class Checkpoint3UnitTests(unittest.TestCase):
    def test_crc16_ccitt_false_check_vector(self):
        self.assertEqual(crc16_ibm_3740(b"123456789"), 0x29B1)

    def test_cesar_manual_round_trip_ascii_and_unicode(self):
        texto = "áéíóXYZ🙂a"
        self.assertEqual(decifrar(cifrar(texto)), texto)

    def test_packet_carries_ciphertext_and_server_recovers_plaintext(self):
        texto = "á🙂"
        pacote = montar_pacote(2, texto)
        self.assertNotIn(texto.encode("utf-8").hex(), pacote)
        self.assertEqual(parsear_pacote(pacote)[0:2], (2, texto))

    def test_corrupted_data_is_rejected_by_crc_before_decryption(self):
        pacote = montar_pacote(2, "teste")
        corrompido = corromper_pacote(pacote)
        with self.assertRaises(FrameError) as contexto:
            parsear_pacote(corrompido)
        self.assertEqual(contexto.exception.reason, "CHECKSUM")

    def test_fragments_are_limited_by_unicode_characters(self):
        fragmentos = dividir_mensagem("áéíóXYZ🙂a")
        self.assertEqual(fragmentos, ["áéíó", "XYZ🙂", "a"])
        self.assertTrue(all(1 <= len(fragmento) <= 4 for fragmento in fragmentos))

    def test_selective_repeat_buffers_out_of_order_and_reacks_duplicates(self):
        lado_servidor, lado_cliente = socket.socketpair()
        lado_servidor.settimeout(2)
        lado_cliente.settimeout(2)
        stats = {
            "pacotes_aceitos": 0,
            "erros_crc": 0,
            "quadros_invalidos": 0,
            "pacotes_fora_de_ordem": 0,
            "duplicatas": 0,
            "acks_enviados": 0,
            "nacks_enviados": 0,
            "timeouts_receptor": 0,
        }
        resultado = {}

        def receber_no_servidor():
            try:
                resultado["texto"] = receber_repeticao_seletiva(
                    lado_servidor, "teste socketpair", 2, 2, stats
                )
            except Exception as erro:  # propagado para a asserção no teste
                resultado["erro"] = erro

        thread = threading.Thread(target=receber_no_servidor)
        thread.start()
        try:
            enviar(montar_pacote(2, "WXYZ"), lado_cliente)
            enviar(montar_pacote(2, "WXYZ"), lado_cliente)
            enviar(montar_pacote(1, "abcd"), lado_cliente)
            respostas = [receber(lado_cliente) for _ in range(3)]
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive(), "O receptor SR não concluiu.")
            self.assertNotIn("erro", resultado)
            self.assertEqual(resultado["texto"], "abcdWXYZ")
            self.assertEqual(respostas, ["ACK|SR|2", "ACK|SR|2", "ACK|SR|1"])
            self.assertEqual(stats["pacotes_fora_de_ordem"], 1)
            self.assertEqual(stats["duplicatas"], 1)
        finally:
            lado_servidor.close()
            lado_cliente.close()


if __name__ == "__main__":
    unittest.main()
