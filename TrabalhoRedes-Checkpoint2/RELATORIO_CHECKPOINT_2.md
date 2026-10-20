# Relatório - Checkpoint 2: Protocolo sem Erros

Infraestrutura de Comunicação - 2026.2<br>
Grupo: G4
Participantes: Bruno Augusto, Gustavo Torres Castro, Arthur Moury Fernandes de Godoy Santos, Diego Ferreira Magnata, Maria Augusta Hatem da Fonte, Pedro José Oliveira e Silva, Luiza Barbosa Almeida da Silva, Luís Eduardo Vieira Melo, Gabriel Mendes Cavalcanti, Rodrigo Vinhas Marques e Eraldo Carneiro Leão Neto<br>
Monitor responsável: Danilo Araujo Duleba<br>

## 1. Contexto e objetivo do Checkpoint 2

O Checkpoint 1 estabeleceu a conexão TCP e negociou modo de operação, limite máximo do texto e tamanho da janela. Esta etapa dá continuidade a esse handshake: o cliente envia uma mensagem textual fragmentada em pacotes de aplicação, o servidor verifica a integridade, confirma os pacotes de acordo com o modo negociado e remonta o texto.

O escopo implementado nesta versão corresponde ao caminho sem perdas e sem corrupção. A especificação do protocolo também registra respostas negativas e timeout para definir o comportamento da aplicação. A simulação de falhas e a recuperação por retransmissão ficam para o Checkpoint 3.

## 2. Base anterior e decisões de reaproveitamento

A implementação de referência utilizada para orientar a transferência é o repositório [TrabalhoRedes de luisvmelo](https://github.com/luisvmelo/TrabalhoRedes). O repositório [trabalho-redes do grupo](https://github.com/BrunoAU/trabalho-redes) contém a entrega de Checkpoint 1 e é o repositório de destino. A cópia CP1 foi mantida sem alterações; a evolução foi organizada em `TrabalhoRedes-Checkpoint2` como entrega separada.

| Recurso da versão anterior | Decisão no CP2 |
|---|---|
| Sockets TCP, handshake e seleção GBN/SR | Mantidos a partir da entrega CP1 do grupo |
| Delimitador NUL, `sendall()` e buffer por conexão | Mantidos para delimitar mensagens da aplicação sobre o fluxo TCP |
| Fragmentação em pacotes de até 4 caracteres | Reintroduzida e alinhada ao limite atual |
| SHA-256 truncado do projeto antigo | Substituído por CRC-16 manual, cobrindo sequência e campo DATA |
| Cifra Fernet e chave embutida na versão antiga | Não reaproveitadas; criptografia não integra o escopo CP2 |
| Go-Back-N e Repetição Seletiva da referência | Reestruturados para confirmar lote e pacotes individuais, respectivamente |
| Temporizadores e retransmissões da referência | Timeout é definido; retransmissões e simulador de falhas permanecem para CP3 |

## 3. Especificação do protocolo CP2

### 3.1 Conexão e enquadramento

A aplicação utiliza sockets IPv4/TCP. O handshake do CP1 negocia o modo, o limite máximo da mensagem (mínimo de 30 caracteres) e uma janela entre 1 e 5, com padrão 5. O cliente envia cada mensagem de aplicação como UTF-8 seguida do byte NUL. As funções de recepção acumulam bytes até o delimitador e preservam o restante no buffer da conexão, sem presumir que uma chamada `recv()` corresponda a uma mensagem.

### 3.2 Mensagens da transferência

| Direção | Mensagem | Significado |
|---|---|---|
| Cliente → servidor | `BEGIN|<caracteres>|<pacotes>` | Declara o tamanho real e a quantidade de fragmentos |
| Cliente → servidor | `SEQ:<n>|DATA:<hex_utf8>|CHK:<crc>` | Envia payload UTF-8 em hexadecimal, sequência e CRC |
| Cliente → servidor | `WINDOW_END|<base>|<último>` | Delimita um lote Go-Back-N |
| Servidor → cliente | `ACK|GBN|<último_seq>` | Confirma cumulativamente o lote recebido |
| Servidor → cliente | `ACK|SR|<seq>` | Confirma individualmente um pacote recebido |
| Servidor → cliente | `NACK|<seq>|<motivo>` | Rejeita pacote/janela inválida; recuperação será CP3 |
| Servidor → cliente | `COMPLETE|<caracteres>|<pacotes>` | Confirma a remontagem da mensagem |

Os campos textuais são delimitados por `|`; o frame completo termina em NUL. O payload de até quatro pontos de código Unicode é codificado em UTF-8 e representado em hexadecimal, evitando colisões com os separadores e com o byte delimitador. A mensagem não pode ser vazia e não pode exceder o limite negociado.

### 3.3 Integridade: CRC-16 manual

O arquivo `checksum.py` calcula CRC-16/IBM-3740, também chamado CRC-16/CCITT-FALSE, em laço bit a bit, sem biblioteca de checksum. O campo protegido é a representação ASCII canônica `SEQ:<n>|DATA:<hex_utf8>`; `CHK` não faz parte da própria entrada do cálculo.

| Parâmetro | Valor |
|---|---|
| Largura | 16 bits |
| Polinômio | `0x1021` |
| Valor inicial | `0xFFFF` |
| Reflexão de entrada/saída | não / não |
| XOR final | `0x0000` |
| Vetor de referência | ASCII `123456789` resulta em `0x29B1` |

O emissor transmite quatro dígitos hexadecimais maiúsculos. O servidor exige o prefixo `CHK:`, valida a representação hexadecimal de DATA, recalcula o CRC e só então decodifica e aceita o payload. CRC é detecção de alteração acidental; não é cifra nem autenticação criptográfica.

O CRC é calculado por uma implementação bit a bit, sem biblioteca externa de checksum ou código pronto de CRC. Ferramentas de IA apoiaram o estudo do algoritmo e a análise técnica da implementação. A validação desta versão inclui o vetor ASCII 123456789, com resultado 0x29B1, e casos de checksum alterado nos dois modos. Conforme o enunciado, a pontuação extra por integridade será avaliada na entrega final.

### 3.4 Go-Back-N

No caminho sem erros ou perdas executado no CP2:

1. O cliente envia até `W` pacotes consecutivos e um `WINDOW_END` com a base e o último número de sequência do lote.
2. O servidor lê o lote completo, verifica formato, sequência, payload e CRC de cada DATA e confere os limites declarados pelo marcador.
3. Se todos os pacotes forem válidos, o servidor os incorpora à mensagem em ordem e envia `ACK|GBN|<último_seq>`.
4. O cliente só avança para a janela seguinte depois de validar o ACK cumulativo esperado.

Regras definidas para o protocolo quando houver falhas: se o servidor encontrar um DATA inválido, sequência inesperada ou limites de janela inconsistentes, rejeita o lote e envia `NACK|<base>|<motivo>`. Se o lote não for concluído dentro do temporizador, envia `NACK|<base>|TIMEOUT`. Ao receber NACK ou expirar o temporizador de ACK, o emissor retransmite todos os pacotes ainda não confirmados desde a base do lote, repete o `WINDOW_END` e reinicia a espera. O receptor só confirma cumulativamente um lote completo e válido; pacotes duplicados ou fora de ordem não são incorporados à mensagem.

Nesta versão CP2, o caminho normal é implementado de ponta a ponta. O código também detecta CRC inválido e timeout e envia NACK, mas encerra a sessão após uma rejeição. A simulação configurável de falhas e a recuperação por retransmissão pertencem ao CP3.

### 3.5 Repetição Seletiva

No caminho sem erros ou perdas executado no CP2:

1. O cliente mantém até `W` DATA sem ACK e preenche os espaços liberados conforme chegam confirmações.
2. O servidor valida cada pacote em ordem e envia `ACK|SR|<seq>` para cada DATA válido.
3. O cliente aceita somente ACKs de sequências que ainda estejam pendentes; cada confirmação libera espaço na janela.

Regras definidas para o protocolo quando houver falhas: o receptor mantém uma janela de recepção com base na menor sequência ainda não entregue. Um pacote íntegro com sequência dentro da janela é armazenado pela sequência e recebe ACK individual; segmentos contíguos são acrescentados à mensagem quando a lacuna anterior é preenchida. Uma cópia duplicada já recebida é descartada e recebe novamente seu ACK, sem duplicar o texto. Pacotes inválidos recebem `NACK|<seq>|<motivo>`; uma sequência fora da janela recebe `NACK|<seq>|WINDOW`. Ao receber NACK ou expirar o temporizador individual de uma sequência pendente, o emissor retransmite somente esse DATA e reinicia seu temporizador. O avanço da janela ocorre quando a base e as sequências contíguas seguintes estão confirmadas.

Nesta versão CP2, o receptor processa em ordem e o cliente mantém a janela de envio, mas a reordenação em buffer e a recuperação individual não são exercitadas. Um DATA inválido ou timeout gera NACK e encerra a sessão; simulação de falhas, buffer fora de ordem e retransmissão pertencem ao CP3.

### 3.6 Temporizador e estados

O temporizador de ACK é de 5 segundos. No CP2, a ausência de ACK ou de DATA encerra a sessão após a resposta NACK aplicável; não há retransmissão nesta etapa. As regras de recuperação previstas para o protocolo são:

- **Go-Back-N:** temporizador da janela pendente; em NACK ou timeout, retransmitir o lote completo desde a base ainda não confirmada.
- **Repetição Seletiva:** temporizador por DATA pendente; em NACK ou timeout, retransmitir apenas a sequência afetada.

A FSM da transferência sem falhas é:

`HANDSHAKE_CONCLUÍDO → AGUARDANDO_BEGIN → ENVIANDO/RECEBENDO_JANELA → VALIDANDO → ACK → (PRÓXIMA_JANELA | REMONTAGEM) → COMPLETE`

Uma entrada inválida leva a `NACK → ENCERRAMENTO` nesta versão. No protocolo completo, uma rejeição inicia o procedimento de recuperação correspondente ao modo selecionado; a simulação e a recuperação funcional são escopo de CP3.

## 4. Implementação desta versão

| Arquivo | Responsabilidade |
|---|---|
| `cliente.py` | Handshake, validação do texto, fragmentação, envio GBN/SR, timeout e exibição dos ACKs |
| `server.py` | Handshake, validação de BEGIN e pacotes, CRC, ACK/NACK e remontagem |
| `checksum.py` | CRC-16 manual compartilhado pelo cliente e servidor |
| `README.md` | Escopo, execução e formato das mensagens |
| `EXEMPLO_TESTE.md` | Roteiro de verificação manual do caminho CP2 |

## 5. Análise crítica e debugging

### 5.1 Framing TCP

TCP fornece um fluxo de bytes, não fronteiras de mensagens de aplicação. Por isso, o delimitador NUL, `sendall()` e o buffer por conexão da entrega CP1 foram preservados. O DATA usa hexadecimal para que o payload não introduza o delimitador ou os separadores do protocolo.

### 5.2 Cobertura do checksum

A referência anterior utilizava SHA-256 truncado sobre o payload em claro. Nesta versão, o CRC-16 manual é calculado sobre a representação ASCII canônica de sequência mais DATA hexadecimal, protegendo ambos os campos transmitidos. O receptor recalcula o valor antes de decodificar e aceitar o payload. CRC detecta alterações acidentais; não é cifra nem autenticação criptográfica.

### 5.3 GBN e SR

O protocolo antigo não delimitava os lotes GBN no fluxo TCP de forma explícita. Nesta versão, `WINDOW_END` indica o fim do lote antes do ACK cumulativo. Em SR, o cliente usa uma janela deslizante e espera ACK por sequência. O servidor processa os dados em ordem, adequado ao caminho sem falhas do CP2; reordenação e recuperação seletiva real continuam pendentes para CP3.

### 5.4 Falhas encontradas e corrigidas durante a validação

- Em execução com saída redirecionada no Windows, a codificação local não representava o cabeçalho Unicode e encerrava o servidor. Cliente e servidor passaram a configurar a saída como UTF-8; os logs do servidor também são descarregados linha a linha.
- Em execução automatizada com entrada redirecionada, a codificação local podia alterar acentos antes da transmissão. O cliente passou a ler stdin redirecionado como UTF-8. Os cenários com acentos e emoji foram repetidos e chegaram íntegros ao servidor.
- A inspeção estática encontrou um parser que não exigia o prefixo `CHK:`. A validação de pacotes malformados confirmou a rejeição do rótulo incorreto após o ajuste.

O temporizador de 5 segundos encerra a sessão com NACK quando nenhum pacote chega; retransmissões e injeção configurável de corrupção/perda continuam fora do CP2. Os cenários de rede foram executados em localhost; conexão entre máquinas diferentes não foi exercitada nesta validação.

## 6. Validação e testes

Em 20/10/2026, os seguintes cenários foram executados nesta versão:

| Cenário executado | Resultado observado | Status |
|---|---|---|
| GBN, janela 5, mensagem de 30 caracteres | ACK cumulativo e `COMPLETE`; texto recomposto no servidor | Aprovado |
| SR, janela 5, texto com acentos e emoji | ACKs individuais; UTF-8 preservado na mensagem recomposta | Aprovado |
| GBN, janela 1, entrada de 31 caracteres seguida de 29 | Entrada de 31 recusada no cliente; transferência seguinte concluída | Aprovado |
| SR, janela 1, mensagem com fragmento final curto | ACK individual por pacote e remontagem correta | Aprovado |
| Vetor CRC ASCII `123456789` | Resultado `0x29B1` | Aprovado |
| CRC adulterado em GBN e SR | Ambos os modos responderam `NACK|1|CHECKSUM` | Aprovado |
| Ausência de DATA após `BEGIN` | Servidor respondeu `NACK|1|TIMEOUT` após o temporizador de 5 segundos | Aprovado |
| Parser de pacote | Prefixo `CHK` inválido, checksum divergente, SEQ não canônico e UTF-8 inválido foram rejeitados | Aprovado |

Os fluxos GBN/SR foram executados em localhost com processos separados. Os casos de checksum inválido e timeout foram exercitados por uma conexão TCP direta após o handshake. A validação não incluiu conexão entre computadores diferentes nem simulador de perdas/corrupção no cliente. A recuperação por retransmissão e a reordenação em SR permanecem para CP3.

## 7. Manual de utilização

Pré-requisito: Python 3. Não há dependências externas.

1. Abra um terminal na pasta `TrabalhoRedes-Checkpoint2` e execute `python server.py`.
2. Em outro terminal, na mesma pasta, execute `python cliente.py`.
3. No cliente, selecione Go-Back-N ou Repetição Seletiva e informe um limite de pelo menos 30 caracteres.
4. No terminal do servidor, pressione ENTER para janela 5 ou informe um número de 1 a 5.
5. Digite uma mensagem não vazia dentro do limite negociado.
6. Observe no servidor os dados e a remontagem; no cliente, acompanhe os ACKs e a confirmação `COMPLETE`.

Para executar em máquinas diferentes, configure `SERVER_HOST` em `cliente.py` com o IPv4 da máquina servidora e permita a conexão TCP na porta 8080.

## 8. Processo de construção e uso de IA

### 8.1 Estratégia de aprendizado com IA

Ferramentas de IA foram utilizadas como apoio para estudar o escopo da especificação, comparar a implementação de referência, discutir o formato dos pacotes e as regras de GBN/SR, apoiar alterações incrementais e revisar o código. As sugestões foram confrontadas com o protocolo definido e com execuções locais; os resultados verificáveis estão registrados na seção 6. As decisões consolidadas são apresentadas na seção 8.3.

### 8.2 Aprendizado técnico

- TCP é um fluxo de bytes; o framing da aplicação continua sendo necessário.
- Fragmentação separa a mensagem do usuário em payloads de no máximo quatro caracteres.
- Sequência identifica os pacotes; ACK positivo confirma recepção e NACK informa rejeição.
- GBN confirma cumulativamente por lote; SR confirma individualmente e move uma janela deslizante.
- O CRC manual opera sobre uma representação canônica e permite ao receptor detectar diferenças nos campos protegidos.
- Timeout é temporização da aplicação; retransmissão com simulação de perda/corrupção será assunto do CP3.

### 8.3 Análise e decisões de implementação

O repositório `luisvmelo/TrabalhoRedes` foi consultado como implementação de referência; `BrunoAU/trabalho-redes` contém a entrega CP1 do grupo e é o repositório de destino. A versão CP2 foi organizada em pasta própria para preservar a entrega anterior.

As decisões desta versão foram manter o handshake e o framing TCP do CP1; substituir o checksum da referência por CRC-16 manual sobre sequência e DATA; delimitar explicitamente os lotes GBN com `WINDOW_END`; implementar ACK cumulativo para GBN e ACK individual com janela deslizante para SR; e separar o caminho sem falhas demonstrado no CP2 das regras de simulação e recuperação do CP3.

### 8.4 Análise crítica e debugging

Uma primeira versão do parser, elaborada com apoio de IA, verificava a sequência, DATA e os quatro dígitos do checksum, mas não exigia o rótulo `CHK:`. A revisão do formato do pacote identificou essa falha; o parser passou a validar o rótulo e a bateria confirmou a rejeição de quadros com esse campo incorreto. A execução em Windows também revelou problemas de codificação ao imprimir o cabeçalho e ao ler entrada UTF-8 redirecionada. As configurações de saída/entrada foram ajustadas e os fluxos com acentos e emoji foram executados com o conteúdo preservado.

Outra decisão crítica foi não trazer a cifra Fernet do código legado: além de não fazer parte do CP2, a versão antiga mantinha uma chave embutida no código, que não foi copiada. A criptografia simétrica manual é uma pontuação extra separada e não foi implementada nesta etapa.

### 8.5 Registro de prompts e conversas

#### Prompt inicial: análise e delimitação do escopo

> [https://github.com/BrunoAU/trabalho-redes](https://github.com/BrunoAU/trabalho-redes)
>
> Precisamos fazer o checkpoint 2 desse trabalho, coloquei o github atual do projeto e as entregas que fizeram nosso checkpoint 1 ter nota máxima, abaixo vou colocar o projeto que estamos usando de um periodo passado para saber o que fazer, considere que estamos focando apenas no escopo de checkpoint 2, o checkpoint 1 entra no escopo como já concluído
>
> [https://github.com/luisvmelo/TrabalhoRedes.git](https://github.com/luisvmelo/TrabalhoRedes.git)
>
> Esse é o github do projeto que estamos fazendo como base, considere que vamos mudar/adicionar o que precisamos de fato para o escopo novo de acordo com o Trabalho de 2026 porque provavelmente tiveram algumas mudanças entre o que foi entregue período passado e o que temos que entregar agora, então avalie isso de acordo com o github de onde estamos pegando o trabalho, não implemente agora, vamos decidir e deixar fechado já o escopo do trabalho para garantir a qualidade

Esse pedido delimitou a análise inicial aos requisitos de CP2 e à comparação entre o projeto do grupo e a implementação de referência.

#### Outros prompts principais

1. “Em relação à pontuação extra, precisamos começar a trabalhar nelas desde já na parte voltada para checksum.”
2. “Considere o checksum como CP2 e vamos começar a implementar essa seção agora junto de CP2 [...] antes das alterações vamos deixar tudo bem definido para a implementação.”
3. “Você tem que olhar para o `luisvmelo/TrabalhoRedes` que é a versão que estamos nos baseando.”
4. “Agora faça as alterações na pasta/projeto atual voltado para Bruno sem enviar ao github [...] faça em .md e depois eu transformo em PDF, comece a implementação para CP2 alterando e adicionando código.”
5. “Feche e valide, execute e deixe fechada e garantida para fecharmos toda a parte como fizemos com o checkpoint 1.”

Os registros mostram os principais prompts usados para delimitar o escopo, orientar a implementação, revisar a referência, registrar o processo e solicitar a validação.

## 9. Limitações e evolução incremental

O caminho CP2 sem erros/perdas e as respostas NACK de checksum/timeout foram exercitados localmente conforme a seção 6. O Checkpoint 3 deve acrescentar e demonstrar simulação determinística de corrupção/perda, recuperação por retransmissão GBN/SR e recepção fora de ordem em SR. A cifra simétrica manual, que corresponde a outra pontuação extra, não foi iniciada.
