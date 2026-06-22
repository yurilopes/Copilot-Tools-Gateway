# Guia De Estilo De Codigo

Este documento descreve o estilo de codigo esperado para agentes que trabalharem no repositório.

## Filosofia

Codigo bom aqui e codigo que um humano consegue ler, auditar e alterar com seguranca.

Prioridade:

1. Correcao.
2. Seguranca.
3. Legibilidade humana.
4. Separacao de responsabilidades.
5. Facilidade de teste.
6. Performance.
7. Concisao.

Concisao nunca deve vencer clareza. Abstracoes inteligentes nunca devem vencer dominio claro.

## Estilo Esperado

Este repositorio deve seguir um estilo operacional direto, modular e orientado ao dominio:

- Funcoes de entrada pequenas que roteiam para handlers por acao ou evento.
- Handlers separados por responsabilidade operacional.
- Modelos de persistencia separados dos handlers.
- Fluxo procedural direto, facil de seguir de cima para baixo.
- Validacao antecipada de dados obrigatorios.
- Retorno rapido em erro de autorizacao, payload invalido ou limite excedido.
- Nomes ligados ao dominio e ao protocolo.
- Funcoes auxiliares pequenas para transformacoes comuns.
- Logs em pontos de transicao importantes.
- Estados e violacoes representados explicitamente.
- Pouca abstracao generica.

Esses pontos devem ser preservados como sensacao geral de codigo.

## O Que Nao Aceitar

Mesmo preservando simplicidade e clareza, estes pontos nao devem ser reproduzidos:

- Segredos, chaves ou tokens versionados.
- `except` amplo fora de fronteiras superiores.
- Tipagem frouxa.
- Imports wildcard.
- TODOs permanentes em codigo de producao.
- Logs com risco de payload sensivel.
- Comentarios que narram codigo evidente.
- Compatibilidade temporaria deixada como permanente.

O Estante Viva deve manter clareza e fluxo direto, mas com disciplina forte de seguranca, tipagem e fronteiras.

## Organizacao

Prefira organizar codigo por dominio e responsabilidade:

- `auth`
- `catalog`
- `payments`
- `credits`
- `library`
- `uploads`
- `ai-jobs`
- `support`
- `admin`
- `suppliers`
- `shared`

Cada modulo deve ter uma razao clara para existir. Evite pastas genericas como `utils` crescendo sem criterio. Quando helpers forem inevitaveis, agrupe por dominio ou capacidade.

## Fluxo De Codigo

Prefira:

- Entrada clara.
- Validacao cedo.
- Normalizacao de dados.
- Chamada para servico ou caso de uso.
- Persistencia ou integracao isolada.
- Retorno claro.

Evite:

- Fluxos escondidos em callbacks desnecessarios.
- Abstracoes prematuras.
- Objetos globais mutaveis sem necessidade.
- Condicionais longas que misturam dominio, persistencia e transporte.
- Fallbacks silenciosos.

## Nomes

Use nomes orientados ao dominio:

- `reserveCredits`
- `confirmPayment`
- `createAudiobookJob`
- `syncSupplierBook`
- `getUserLibraryItem`
- `blockForbiddenContent`

Evite nomes vagos:

- `processData`
- `handleStuff`
- `doThing`
- `manager`
- `helper`

## Tipagem E Contratos

Use tipagem forte e contratos explicitos.

Categorias de integracao com multiplas implementacoes devem expor contrato comum, pequeno e estavel. O dominio deve depender desse contrato, nao de fornecedores, gateways ou providers concretos.

Separe tipo de integracao de instancia configurada. A implementacao representa o tipo. A instancia representa uma conta, configuracao, credencial, estado e identificador especificos.

Em TypeScript:

- Evite `any`.
- Evite assertions para esconder problema.
- Prefira tipos de dominio.
- Use schemas de validacao nas fronteiras.
- Normalize dados externos antes de entrar no dominio.

Em Python:

- Evite `Any`.
- Evite `cast`.
- Evite `type: ignore`.
- Prefira tipos precisos.
- Use excecoes especificas.

Quando uma biblioteca externa retornar dados dinamicos, trate essa fronteira como contaminada:

1. Receba o valor.
2. Valide.
3. Normalize.
4. Converta para tipo interno.
5. Passe adiante somente o tipo interno.

## Integracoes Modulares

Ao implementar fornecedores, gateways, provedores de IA ou integracoes similares:

- defina ou reutilize a interface comum;
- mantenha detalhes externos dentro do adaptador concreto;
- registre a implementacao em mecanismo de resolucao;
- represente contas configuradas separadamente da implementacao;
- permita ativacao e desativacao por estado persistido;
- escreva testes de contrato;
- evite condicionais espalhadas por nome de provider.

Capacidades opcionais devem ser explicitas. Nao obrigue uma implementacao a fingir suporte a recurso que nao possui.

## Erros

Erros internos devem ser especificos.

Exemplos:

- `PaymentNotConfirmed`
- `InsufficientCredits`
- `SupplierBookUnavailable`
- `ForbiddenGeneratedAssetAccess`
- `UnsupportedUploadedFile`

Converta erros para HTTP, MCP ou outro formato de transporte apenas na fronteira superior.

Nao use erro generico para controle normal de fluxo.

## Fallbacks

Fallback so e aceitavel quando:

- e seguro;
- e explicito no nome;
- e documentado;
- nao mascara perda de dados;
- nao libera acesso pago;
- nao reduz seguranca.

Nomes bons:

- `tryBestEffortNotification`
- `loadCachedCatalogSnapshot`
- `safePaymentReconciliationRetry`

Nomes ruins:

- `fix`
- `fallback`
- `ignoreError`

## Testes

Testes devem proteger contratos reais.

Nao altere core logic para facilitar mock. Em vez disso:

- injete dependencias em fronteiras adequadas;
- use interfaces pequenas;
- teste dominio sem infraestrutura;
- teste integracoes com adaptadores ou ambientes controlados;
- corrija contratos alpha incorretos em vez de preserva-los artificialmente.

## Tamanho Dos Arquivos

Meta: ate 400 linhas fisicas por arquivo de codigo fonte.

Limite maximo: 450 linhas fisicas.

Se passar de 400 linhas, explique na revisao ou progresso. Se passar de 450 linhas, refatore preservando coesao logica.

Nao divida arquivo apenas para cumprir numero. Divida quando houver fronteira natural:

- tipos;
- validacao;
- caso de uso;
- repositorio;
- provider;
- handler;
- testes.

## Comentarios

Comentarios devem ser em ingles, curtos e explicar somente:

- regra funcional ou de negocio;
- boundary de seguranca ou ownership;
- motivo de lock ou decisao de concorrencia;
- risco de operacao destrutiva;
- motivo de recovery ou fallback best-effort seguro.

Nao escreva comentario para narrar o que o codigo ja diz.

## Logs

Logs devem registrar:

- inicio e fim de operacoes importantes;
- transicoes de status;
- falhas de integracao;
- bloqueios de seguranca;
- reconciliacoes de pagamento;
- jobs assincronos;
- IDs internos seguros.

Logs nao devem registrar:

- tokens;
- cookies;
- segredos;
- documentos completos;
- payloads completos;
- prompts completos;
- conteudo sensivel;
- metadados sigilosos de fornecedor;
- codigo JavaScript completo;
- storage bruto.

## Checklist Para Agentes

Antes de finalizar uma mudanca de codigo:

- O codigo segue fluxo direto e legivel?
- A validacao acontece cedo?
- Tipos estao precisos?
- O LSP esta satisfeito?
- Lint e testes relevantes foram respeitados?
- Algum arquivo passou de 400 linhas?
- Alguma regra de negocio foi dobrada para teste?
- Algum dado sensivel entrou em log?
- Alguma informacao de fornecedor vazou?
- Alguma funcionalidade paga pode ser usada sem pagamento ou credito?
- A documentacao afetada foi atualizada?
