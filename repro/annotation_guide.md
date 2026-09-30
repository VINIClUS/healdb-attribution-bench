# Guia de anotação documental — Q3 (protocolo v0.2, §12)

Versão 0.1 do guia, para o piloto de anotação. Qualquer mudança depois do piloto recebe nova versão e fica
registrada em `deviations.md`, com a data e o motivo.

## 1. Objetivo

Registrar, para cada texto, **todas** as doenças ou condições que a seção de indicações da bula em português
apresenta como indicação do medicamento. A referência é a bula, não a eficácia terapêutica nem o conhecimento clínico
do anotador.

A anotação é completa, e não uma validação de associações já emitidas. Sem a lista completa, não há como medir a
revocação do sistema (§12).

## 2. O que o anotador recebe

A planilha cega (CSV) traz, por linha:

| coluna | conteúdo |
|---|---|
| `blind_id` | identificador opaco da unidade (não revela medicamento, grupo, estrato nem partição) |
| `annotator` | seu identificador |
| `document_ref` | referência do documento fixada por versão (hash/versão da bula usada) |
| `text` | a seção de indicações em português a anotar |
| `codes` | **preencher**: códigos CID-10 separados por `;` |
| `evidence` | **preencher**: trecho(s) literal(is) do texto que sustenta(m) cada código |
| `notes` | opcional: dúvidas, ambiguidades, casos de borda |

A planilha **não** mostra saídas do sistema, estratos, pesos de amostragem nem se a unidade terá anotação dupla.
Não procure essas informações e não consulte outros anotadores antes de entregar.

## 3. Unidade de anotação: categoria CID-10

- **Unidade principal:** a categoria CID-10 da OMS, com três caracteres (ex.: `C61`, `J45`, `E11`).
- **Subcategoria** (quatro caracteres, ex.: `E11.9` → escrever `E119` ou `E11.9`): use-a **somente quando o texto
  sustenta** esse nível de detalhe. Se o texto diz apenas "diabetes tipo 2", anote `E11`, não uma subcategoria.
- Formato aceito: letra + dois dígitos, com um quarto caractere opcional. Pontos são removidos na leitura.
  Códigos fora desse formato são rejeitados com indicação da linha.
- Use a CID-10 da OMS (a terminologia de comparação principal, `docs/decisoes.md`). Não use códigos exclusivos da
  CID-10-CM.
- Se uma indicação não tiver código adequado, não force um código: descreva em `notes`.

## 4. O que conta como indicação

Conta:

- doença, condição, sintoma ou estado que o texto apresenta como motivo de uso ("indicado para", "tratamento de",
  "alívio de", "prevenção de", "coadjuvante no tratamento de");
- condições listadas em enumerações, cada uma com seu próprio código;
- indicações restritas a uma população ("em adultos com…"): anote a condição; a restrição vai em `notes` se relevante.

Não conta:

- **menções em contraindicações, advertências, precauções ou interações**, mesmo que apareçam no trecho;
- condições citadas como efeito adverso, como exemplo de risco ou como histórico familiar;
- condições negadas ("não é indicado para…");
- **inferências a partir de conhecimento externo**: se o texto diz "antibiótico" sem citar infecções, não anote
  infecções; se diz o princípio ativo, não anote as indicações conhecidas desse princípio;
- mecanismo de ação ("inibe a enzima X") sem condição nomeada.

Em caso de dúvida real entre contar e não contar, **não anote** e registre a dúvida em `notes`. A adjudicação resolve.

## 5. Evidência

Para cada código, copie em `evidence` o trecho literal que o sustenta, no formato `CÓDIGO: "trecho"`, separando
códigos por `;`. O trecho deve existir no texto exatamente como aparece, sem paráfrase.

## 6. Documento de referência fixado por versão

- Anote apenas o texto fornecido na linha. O `document_ref` identifica a versão exata; não use outra versão da bula,
  nem a bula completa, nem fontes externas.
- Em cenários com entrada editada (intervenção semissintética), a unidade traz o texto daquela condição, e a
  anotação vale para ele. Um texto editado **não** é bula oficial real e não deve ser apresentado como tal (§12).

## 7. Procedimento

1. **Piloto (20 textos):** todos os anotadores anotam; a equipe discute as divergências e revisa este guia. Os textos
   do piloto **não** entram na avaliação final.
2. **Avaliação (130 textos de grupos de teste, após a abertura do teste):** 50 com anotação dupla independente e 80
   com anotação única. A escolha é amostral, com probabilidades de inclusão registradas.
3. **Concordância antes da adjudicação:** nos 50 duplos, calcula-se a concordância percentual, o kappa de Cohen por
   categoria e o alfa de Krippendorff nominal, sobre os pares (unidade, categoria). Esses números são publicados antes
   de qualquer adjudicação.
4. **Adjudicação:** cada código anotado por só um dos dois recebe decisão explícita do adjudicador (manter ou
   descartar). Códigos concordantes são mantidos. Nada é decidido por omissão.
5. **Limitação:** os 80 textos de anotação única não têm medida de concordância própria. Essa limitação é declarada
   nos resultados.

## 8. Limites

- Q3 mede suporte documental, precisão e revocação contra a bula. Não produz conclusão clínica.
- Se faltarem especialistas, o Q3 é reduzido e a avaliação computacional (H1/H2) continua separada (§12).
