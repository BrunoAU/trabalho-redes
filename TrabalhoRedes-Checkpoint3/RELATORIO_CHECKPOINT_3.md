# Relatório do Checkpoint 3 Erros e Perdas

Infraestrutura de Comunicação - 2026.2<br>
Grupo: G4
Participantes: Bruno Augusto, Gustavo Torres Castro, Arthur Moury Fernandes de Godoy Santos, Diego Ferreira Magnata, Maria Augusta Hatem da Fonte, Pedro José Oliveira e Silva, Luiza Barbosa Almeida da Silva, Luís Eduardo Vieira Melo, Gabriel Mendes Cavalcanti, Rodrigo Vinhas Marques e Eraldo Carneiro Leão Neto<br>
Monitor responsável: Danilo Araujo Duleba<br>

## 1. Contexto e objetivo do Checkpoint 3

O Checkpoint 1 estabeleceu a conexão TCP e negociou o modo de operação, o limite máximo do texto e o tamanho da janela. O Checkpoint 2 acrescentou a transferência de mensagens fragmentadas, a validação por CRC-16 manual e os reconhecimentos GBN e SR. Esta entrega dá continuidade a essas etapas e concentra-se no escopo do Checkpoint 3: injetar corrupção e perda de forma determinística, recuperar a transmissão por retransmissões e implementar uma cifra simétrica manual.

As entregas anteriores permanecem concluídas e preservadas em suas pastas. O código do CP3 mantém o handshake e o framing TCP do grupo, e adapta a implementação de referência de Luis Melo ao protocolo e às decisões já consolidados no CP2. O CRC-16 manual é mantido e passa a proteger o DATA cifrado; a cifra de César módulo 256 foi acrescentada como o outro algoritmo manual de pontuação extra.

## 2. Base anterior e decisões de reaproveitamento

O repositório [TrabalhoRedes de Luis Melo](https://github.com/luisvmelo/TrabalhoRedes) foi usado como referência técnica. O repositório [trabalho-redes do grupo](https://github.com/BrunoAU/trabalho-redes) contém a entrega CP1 e é o projeto de destino. A tabela resume o que foi preservado e o que foi adaptado nesta etapa.

| Recurso da base | Decisão no CP3 |
|---|---|
| Sockets TCP, handshake e seleção GBN/SR do grupo | Preservados, mantendo a negociação dos checkpoints anteriores |
| Delimitador NUL, `sendall()` e buffer de recepção por conexão | Preservados para delimitar frames sobre o fluxo TCP |
| Fragmentação de até quatro caracteres e formato de pacotes do CP2 | Mantidos; o payload é cifrado antes de ser representado em hexadecimal |
| CRC-16 manual do CP2 | Mantido; o cálculo cobre a sequência e o DATA cifrado transmitido |
| Seleção determinística de sequências com falha, loops de recuperação e contadores da referência | Adaptados ao frame, aos ACKs/NACKs e aos temporizadores do protocolo do grupo |
| GBN e SR da referência | Reestruturados para rejeição atômica de lote em GBN e buffer individual fora de ordem em SR |
| Cifra Fernet da referência antiga | Não reaproveitada; a entrega usa uma cifra simétrica implementada manualmente |

## 3. Especificação do protocolo CP3

### 3.1 Conexão e enquadramento

A aplicação usa sockets IPv4/TCP. O handshake anterior negocia o modo, um limite de texto de pelo menos 30 caracteres e uma janela entre 1 e 5, com valor padrão 5. Cada frame de aplicação é codificado em UTF-8 e termina com o byte NUL (`\0`). As funções de recepção acumulam bytes até encontrar esse delimitador, sem presumir que uma chamada `recv()` corresponda a uma mensagem completa.

O cliente envia a mensagem em fragmentos de até quatro caracteres Unicode. O tamanho dos fragmentos é definido sobre o texto original; em seguida, cada fragmento é convertido para bytes UTF-8 e cifrado. O campo DATA transporta o hexadecimal dos bytes cifrados.

### 3.2 Mensagens de transferência

| Direção | Formato | Finalidade |
|---|---|---|
| Cliente → servidor | `BEGIN&#124;<caracteres>&#124;<pacotes>` | Declara o tamanho original do texto e o total de fragmentos |
| Cliente → servidor | `SEQ:<n>&#124;DATA:<hex_cifrado>&#124;CHK:<crc16>` | Transporta sequência, payload cifrado e CRC |
| Cliente → servidor | `WINDOW_END&#124;<base>&#124;<último>` | Delimita um lote GBN |
| Servidor → cliente | `ACK&#124;GBN&#124;<último_seq>` | Confirma cumulativamente um lote GBN válido |
| Servidor → cliente | `ACK&#124;SR&#124;<seq>` | Confirma um DATA SR individual |
| Servidor → cliente | `NACK&#124;<seq>&#124;<motivo>` | Rejeita pacote ou janela e informa a sequência/base e o motivo |
| Servidor → cliente | `COMPLETE&#124;<caracteres>&#124;<pacotes>` | Confirma a remontagem integral da mensagem |

Os frames são delimitados por NUL. O CRC é calculado sobre a representação ASCII `SEQ:<n>|DATA:<hex_cifrado>`, sem incluir `CHK`. O servidor recalcula o CRC antes de decifrar o payload.

### 3.3 Integridade por CRC-16 manual

O módulo `checksum.py` implementa CRC-16/IBM-3740, também conhecido como CRC-16/CCITT-FALSE, percorrendo cada byte e seus bits. O cálculo não usa biblioteca externa de checksum.

| Parâmetro | Valor |
|---|---|
| Largura | 16 bits |
| Polinômio | `0x1021` |
| Valor inicial | `0xFFFF` |
| Reflexão de entrada/saída | Não / não |
| XOR final | `0x0000` |
| Vetor de referência | ASCII `123456789` resulta em `0x29B1` |

O CRC protege a sequência e os bytes cifrados representados no DATA. Se sequência, conteúdo ou CRC recebido não corresponderem, o servidor rejeita o pacote antes da decifragem. CRC detecta alterações acidentais; não é mecanismo de autenticação nem cifra.

### 3.4 Cifra simétrica manual

O módulo `cipher.py` implementa uma rotação modular de César diretamente sobre os bytes UTF-8. Para cada byte, a cifra calcula `c = (p + k) mod 256`; a decifragem calcula `p = (c - k) mod 256`. O deslocamento compartilhado é `k = 3`.

Como a transformação opera sobre bytes, os acentos e emojis são cifrados junto com os demais caracteres. Depois da decifragem, os bytes são decodificados como UTF-8 e o servidor recupera o texto original. A cifra foi implementada sem biblioteca de criptografia e tem finalidade didática; não oferece proteção adequada para dados reais.

### 3.5 Go-Back-N

O cliente envia até `W` pacotes consecutivos e um marcador `WINDOW_END` com a base e a última sequência do lote. O servidor verifica a ordem, a quantidade, os limites declarados, a codificação e o CRC dos pacotes recebidos. Só incorpora os fragmentos à mensagem depois de validar o lote inteiro.

Se houver corrupção, sequência ausente, frame inválido ou lote incompleto, o servidor responde com NACK na base da janela e descarta o lote rejeitado sem anexar conteúdo parcial. Ao receber NACK ou atingir o temporizador de ACK, o cliente retransmite toda a janela ainda pendente e repete o marcador. Uma janela completa e válida é incorporada uma vez e recebe ACK cumulativo.

### 3.6 Repetição Seletiva

O emissor mantém até `W` pacotes sem ACK e acompanha um temporizador para cada sequência. O servidor valida cada DATA e confirma individualmente os pacotes íntegros que estão dentro da janela de recepção. Pacotes recebidos fora de ordem são armazenados por sequência; quando chega a sequência que faltava, os fragmentos contíguos são acrescentados à mensagem.

Um NACK ou timeout causa retransmissão somente do DATA afetado. Uma cópia duplicada válida é descartada e recebe novamente seu ACK, sem ser anexada duas vezes. A mensagem só é concluída quando todos os fragmentos previstos forem recebidos e remontados na ordem correta.

### 3.7 Temporizadores, tentativas e estados

O temporizador do emissor é de cinco segundos. O cliente permite até cinco retransmissões por janela GBN ou por sequência SR. A injeção de corrupção ou perda é determinística e ocorre somente na tentativa inicial; assim, a retransmissão envia o pacote sem repetir a falha artificial.

A transferência segue a sequência `HANDSHAKE_CONCLUÍDO → BEGIN → ENVIO/RECEPÇÃO → ACK ou NACK → RETRANSMISSÃO ou PRÓXIMA_JANELA → COMPLETE`. GBN avança após um ACK cumulativo esperado; SR mantém as sequências pendentes até receber seus ACKs individuais.

## 4. Implementação desta versão

| Arquivo | Responsabilidade |
|---|---|
| `cliente.py` | Handshake, validação e fragmentação do texto, cifra, construção do DATA, simulação de falhas, envio GBN/SR, temporizadores e retransmissões |
| `server.py` | Handshake, leitura de frames, validação CRC, decifragem, ACK/NACK, recepção fora de ordem SR, remontagem e estatísticas |
| `checksum.py` | Implementação manual do CRC-16/CCITT-FALSE compartilhada pelo cliente e servidor |
| `cipher.py` | Cifra e decifra manual de César módulo 256 aplicada a bytes UTF-8 |
| `test_checkpoint3.py` | Seis testes unitários de checksum, cifra, pacote, corrupção, fragmentação e SR |
| `test_integration_checkpoint3.py` | Matriz automatizada de 20 sessões TCP com cliente e servidor em processos separados |
| `README.md` | Escopo, execução, formato dos frames e regras de recuperação |
| `EXEMPLO_TESTE.md` | Roteiro manual de testes e cenários esperados |

## 5. Análise crítica e adaptações realizadas

### 5.1 Corrupção e perda na camada de aplicação

A corrupção altera um dígito hexadecimal do DATA cifrado depois de o CRC ser calculado. O servidor recalcula o CRC sobre o campo recebido e rejeita o pacote alterado. A perda omite o DATA escolhido na primeira tentativa, sem alterar o transporte TCP; o servidor identifica o pacote ausente quando recebe o marcador de fim da janela ou quando expira seu temporizador.

Essa simulação torna os cenários repetíveis e permite observar as regras de recuperação de cada algoritmo. Ela representa falhas introduzidas pela aplicação, não perdas físicas na rede nem corrupção realizada pelo TCP.

### 5.2 Ordem da cifra e do checksum

O DATA transmitido contém o texto cifrado. Por isso, o cliente calcula o CRC depois da cifra, incluindo a sequência e o hexadecimal cifrado. O servidor valida essa representação recebida antes de decifrar. A ordem foi conferida por testes que verificam o conteúdo do pacote e a rejeição de um DATA alterado com o motivo `CHECKSUM`.

### 5.3 Diferença entre GBN e SR

GBN trata o lote pendente como uma unidade: um pacote inválido ou ausente rejeita a janela, e o cliente envia novamente todo o lote. SR confirma e recupera sequências individualmente; o buffer permite guardar pacotes posteriores enquanto uma lacuna é corrigida. A validação inclui uma sequência recebida fora de ordem e uma duplicata, confirmando que o ACK pode ser repetido sem duplicar texto.

### 5.4 Referência e escopo

O projeto de Luis Melo serviu de referência para a configuração determinística das falhas, os loops de retransmissão e os contadores. O protocolo do grupo continuou sendo a base da integração: frames delimitados por NUL, CRC manual sobre sequência e DATA, janela negociada e os formatos de ACK/NACK do CP2. A cifra Fernet da versão anterior não foi copiada.

## 6. Validação e testes

Em 23 de novembro de 2026, a suíte automatizada foi executada em Windows com Python 3.12.14. O comando `python -m unittest discover -v -p "test*.py"` terminou com sete métodos de teste aprovados: seis testes unitários e um teste de integração que executou 20 sessões TCP em localhost. Os clientes foram iniciados em processos separados do servidor, e o texto remontado foi comparado ao texto enviado em cada sessão.

| Verificação | Resultado observado | Status |
|---|---|---|
| Vetor CRC ASCII `123456789` | Resultado `0x29B1` | Aprovado |
| Cifra e decifra com acentos e emoji | Texto recuperado idêntico ao original | Aprovado |
| DATA transmitido e CRC antes da decifragem | Pacote contém ciphertext e o servidor recupera o texto original | Aprovado |
| Corrupção de DATA | CRC rejeita o pacote com motivo `CHECKSUM` antes da decifragem | Aprovado |
| Fragmentação Unicode | Fragmentos limitados a quatro caracteres; fragmento final curto preservado | Aprovado |
| Buffer SR e duplicatas | SEQ 2 recebida antes da SEQ 1, re-ACK e remontagem sem duplicar texto | Aprovado |
| GBN, janela 5 | Sessões sem falha, com corrupção, com perda e com ambas as falhas configuradas concluíram; lotes rejeitados foram retransmitidos | Aprovado |
| SR, janela 5 | Sessões sem falha, com corrupção, com perda e com falhas combinadas recuperaram as sequências pendentes | Aprovado |
| Janela 1 | GBN e SR concluíram sem falhas e também após corrupção ou perda | Aprovado |
| Mais de uma janela | GBN e SR avançaram após a primeira janela e remontaram os fragmentos restantes | Aprovado |
| Falha na segunda janela | Corrupção em SEQ 6 no GBN e perda em SEQ 6 no SR foram recuperadas sem repetir a janela já confirmada | Aprovado |
| UTF-8 em cliente-servidor | Acentos e emoji chegaram íntegros em GBN e SR, inclusive com fragmento final menor que quatro caracteres | Aprovado |

A matriz também cobre as combinações de modo, janela e falhas descritas em `EXEMPLO_TESTE.md`. Nos casos combinados GBN, a rejeição é feita por janela; a perda também foi exercitada isoladamente. Nos casos combinados SR, os testes verificaram NACK para a sequência corrompida e timeout para a sequência perdida. Toda a matriz foi executada em localhost; a comunicação entre computadores diferentes não foi testada.

## 7. Manual de utilização

Pré-requisito: Python 3. Não há dependências externas.

1. No primeiro terminal, entre na pasta `TrabalhoRedes-Checkpoint3` e execute `python server.py`.
2. Em outro terminal, na mesma pasta, execute `python cliente.py`.
3. No cliente, selecione GBN ou SR e informe um limite máximo de pelo menos 30 caracteres.
4. No servidor, informe uma janela entre 1 e 5 ou pressione ENTER para usar o padrão 5.
5. Digite uma mensagem não vazia dentro do limite. Para executar sem falhas, responda `n` à pergunta de simulação.
6. Para simular falhas, responda `s`, informe as sequências a corromper e depois as sequências a perder; se não houver sequências de um tipo, deixe o campo vazio.
7. Observe no cliente os ACKs, NACKs, timeouts e retransmissões. No servidor, confira a validação dos pacotes e a mensagem remontada.

Para executar cliente e servidor em computadores diferentes, ajuste `SERVER_HOST` em `cliente.py` para o IPv4 da máquina servidora e permita o acesso à porta configurada. Essa configuração de rede não faz parte da matriz local executada.

## 8. Processo de construção e uso de IA

### 8.1 Estratégia de uso

Ferramentas de IA foram utilizadas como apoio para estudar o escopo 2026.2, comparar o repositório do grupo com a implementação de referência, discutir os fluxos de falha e recuperação, apoiar alterações incrementais e revisar o código e os testes. O grupo delimitou o trabalho ao CP3, confirmou o uso de Luis Melo como referência e definiu a inclusão dos dois algoritmos manuais. As sugestões foram confrontadas com o enunciado, o protocolo e execuções locais. Os comandos e resultados da validação estão registrados na seção 6.

### 8.2 Aprendizado técnico

- TCP transporta um fluxo de bytes; a aplicação continua precisando delimitar seus frames.
- O CRC manual verifica a sequência e o DATA cifrado, e o receptor deve validá-lo antes da decifragem.
- A cifra de César módulo 256 pode ser aplicada aos bytes UTF-8, desde que os bytes originais sejam restaurados antes da decodificação.
- GBN rejeita e retransmite um lote; SR confirma e retransmite sequências individuais.
- Em SR, o buffer por sequência permite receber dados fora de ordem sem montar a mensagem incorretamente.
- Uma matriz determinística permite repetir as mesmas condições de corrupção e perda e conferir os resultados.

### 8.3 Análise e decisões de implementação

As decisões consolidadas foram manter o framing e os formatos do CP2; calcular o CRC sobre o campo cifrado que trafega no DATA; usar transformação manual sobre bytes UTF-8 para o ponto extra de criptografia simétrica; manter a injeção de falhas no cliente e na camada de aplicação; e implementar a rejeição integral de lote em GBN e o buffer/re-ACK em SR.

### 8.4 Análise crítica e debugging

A revisão verificou três fronteiras importantes: o tamanho do fragmento é medido no texto Unicode original; o CRC é calculado sobre a representação realmente transmitida; e a decifragem só ocorre após a validação de integridade. Os testes unitários verificam cada comportamento, enquanto os processos separados confirmam a integração TCP. A matriz de falhas também confere a conclusão da mensagem e a igualdade entre o texto enviado e o remontado pelo servidor.

### 8.5 Registro de prompts e conversas

#### Prompt inicial: análise e delimitação do escopo

> [https://github.com/BrunoAU/trabalho-redes](https://github.com/BrunoAU/trabalho-redes)
>
> Precisamos fazer o checkpoint 3 desse trabalho, coloquei o github atual do projeto e as entregas que fizeram nosso checkpoint 1 e 2 terem nota máxima, abaixo vou colocar o projeto que estamos usando de um periodo passado para saber o que fazer, considere que estamos focando apenas no escopo de checkpoint 3 agora, o checkpoint 1 e 2 entra no escopo como já concluído
>
> [https://github.com/luisvmelo/TrabalhoRedes.git](https://github.com/luisvmelo/TrabalhoRedes.git)
>
> Esse é o github do projeto que estamos fazendo como base, considere que vamos mudar/adicionar o que precisamos de fato para o escopo novo de acordo com o Trabalho de 2026 porque provavelmente tiveram algumas mudanças entre o que foi entregue período passado e o que temos que entregar agora, então avalie isso de acordo com o github de onde estamos pegando o trabalho, não implemente agora, vamos decidir e deixar fechado já o escopo do trabalho para garantir a qualidade
>
> Além do escopo do checkpoint 3 considere que eu quero pegar o ponto extra e por isso não vamos poder usar a biblioteca

Esse pedido delimitou a análise inicial ao CP3, tratando CP1 e CP2 como concluídos e solicitando que o escopo fosse definido antes da implementação.

#### Outros prompts principais

1. “Lembre de usar como base o que temos do repositório de Luis Melo, de resto eu concordo, podemos seguir.”
2. “Agora vamos validar todo o funcionamento e garantir que as implementações do CP3 e relacionadas a pontos extras estão implementadas e alinhadas dentro do escopo previsto”

Os registros mostram os principais prompts usados para delimitar o escopo, orientar o uso da referência, solicitar revisão e validação e preparar a defesa oral.

## 9. Limitações e conclusão

O CP3 foi implementado e validado nos testes locais descritos neste relatório. O CRC detecta alterações acidentais, mas não autentica; a cifra de César é didática e não protege dados reais. A simulação injeta falhas na camada de aplicação e a matriz cobriu apenas localhost, sem teste entre máquinas diferentes. As entregas CP1 e CP2 permanecem concluídas e preservadas.
